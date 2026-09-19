"""Read a Harvey playbook export and check it against the authoring format.

A Harvey rule has five fields: standard position, acceptable deviations, unacceptable
deviations, guidance, and an optional flag. Six further things a maintainable playbook needs
(identity, dependencies, precedence, absence remediation, exhaustion paths, provenance) have no
field, and the authoring format puts them inside Guidance by convention. Harvey cannot validate
any of that, because to the platform it is prose. This module is where it gets checked.

Nothing here touches the database. It parses a document and returns findings, the way
`prompt_check` lints a prompt before it is stored.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .findings import Finding, PromptGraphError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Headings the export renders. Level varies between exports, so match on text not depth.
_FIELD_HEADINGS = {
    "standard position": "standard",
    "acceptable positions": "acceptable",
    "acceptable deviations": "acceptable",
    "unacceptable positions": "unacceptable",
    "unacceptable deviations": "unacceptable",
    "guidance": "guidance",
    "workflow actions": "workflow",
    "required": "required",
    "optional": "optional",
}
_PREAMBLE_HEADINGS = {"ai guidance", "general guidance", "preamble"}

# Guidance conventions, in the order the authoring format specifies them.
_RULE_ID = re.compile(r"^\s*Rule ID:\s*(\S+)", re.M | re.I)
_DEPENDS = re.compile(r"^\s*Depends on:\s*(.+)$", re.M | re.I)
_PRECEDENCE = re.compile(r"^\s*Precedence:\s*(.+)$", re.M | re.I)
_EXHAUSTION = re.compile(r"^\s*On exhaustion:\s*(.+)$", re.M | re.I)
_SOURCE = re.compile(r"^\s*Source:\s*(.+?)(?:\s*·\s*Reviewed:\s*(\S+))?\s*$", re.M | re.I)
_DEP_ITEM = re.compile(r"([A-Za-z0-9_.\-]+)\s*(?:\(([^)]*)\))?")

# Absence remediation. The authoring format prescribes "If the provision is absent: Insert the
# following" plus the wording, but a playbook written before that convention says the same thing
# in its own words, so the functional equivalents count. What does not count is an edit
# instruction ("ADD a carve-out to the existing clause"), which says nothing about absence, or an
# instruction to insert with no wording supplied, which leaves a model drafting the redline.
_ABSENCE = re.compile(
    r"if the (?:provision|clause) is absent"
    r"|if not already"
    r"|if not present"
    r"|if (?:it is )?missing"
    r"|where absent"
    r"|add the below provision"
    r"|insert the following",
    re.I,
)
_OPERATIVE = re.compile('["\u201c][^"\u201c\u201d]{40,}["\u201d]')
# The authoring format gives three answers to absence: acceptable, insert this language, or
# escalate. Only "insert" has to supply wording. A check that demanded wording from all three
# fired on rules that had answered correctly, which is a false absence of an absence answer.
_ABSENCE_ESCALATES = re.compile(r"\bescalat\w+", re.I)
_ABSENCE_ACCEPTABLE = re.compile(r"no action|need not be added|is not required|acceptable", re.I)

# Prose standing in for structure. These are the openings the authoring format names.
_PROSE_GATE = re.compile(
    r"(this rule applies only when|only applies when|applies only if|"
    r"unless the client has|where we have already agreed|see the rule on|"
    r"has been accepted with client approval)",
    re.I,
)

# An entry that says nothing but "reasonable edits".
_ONLY_REASONABLE = re.compile(r"^(?:ok to\s+)?(?:accept|allow)?\s*reasonable edits?\.?$", re.I)

# A ladder with a finite ceiling on one side and only an unbounded floor on the other leaves
# everything between them unaddressed. Accept up to three years, refuse an indefinite term, and
# a counterparty asking for four has fallen through a hole the rule does not know it has.
_BOUNDED = re.compile(
    r"\b(?:up to|no more than|not exceeding|maximum of|at most)?\s*"
    r"(?:\d+|\(\d+\))\s*\(?\d*\)?\s*(year|month|week|day)s?\b"
    r"|\$\s?[\d,]{4,}",
    re.I,
)
_UNBOUNDED = re.compile(
    r"\b(indefinite\w*|perpetual|perpetuity|unlimited|uncapped|forever|"
    r"no (?:time )?limit|without limit)\b",
    re.I,
)

_DOC_CONTROL = re.compile(r"\b(version|owner|effective date|steward|review trigger)\b", re.I)


@dataclass(slots=True)
class Rule:
    name: str
    position: int
    standard: str = ""
    acceptable: list[str] = field(default_factory=list)
    unacceptable: list[str] = field(default_factory=list)
    guidance: str = ""
    workflow: list[str] = field(default_factory=list)
    required: bool | None = None
    # text sitting under the heading before any field heading. For a rule this is usually
    # empty; for a document section it is the whole of the content, which is how the two are
    # told apart after parsing.
    prose: list[str] = field(default_factory=list)

    @property
    def has_fields(self) -> bool:
        return bool(
            self.standard
            or self.acceptable
            or self.unacceptable
            or self.guidance
            or self.workflow
            or self.required is not None
        )

    # parsed out of guidance, per the authoring conventions
    rule_id: str | None = None
    depends_on: list[tuple[str, str | None]] = field(default_factory=list)
    precedence: str | None = None
    on_exhaustion: str | None = None
    source: str | None = None
    reviewed: str | None = None

    @property
    def absence_remediation(self) -> bool:
        """Says what happens when the provision is missing.

        Answering with wording, with escalation, or with "nothing needed" are all answers. Only
        an instruction to insert has to carry the text, because "insert a customary provision"
        leaves a model drafting the outbound redline from a description."""
        m = _ABSENCE.search(self.standard)
        if not m:
            return False
        tail = self.standard[m.start() :]
        if _ABSENCE_ESCALATES.search(tail) or _ABSENCE_ACCEPTABLE.search(tail):
            return True
        return bool(_OPERATIVE.search(tail))


@dataclass(slots=True)
class Playbook:
    name: str
    preamble: str = ""
    rules: list[Rule] = field(default_factory=list)
    # headings that turned out to be document structure rather than rules: Document Control,
    # Rules, an appendix. Kept rather than discarded, because their text is where a document
    # control block lives and a check that cannot see it reports a false absence.
    sections: list[tuple[str, str]] = field(default_factory=list)

    @property
    def front_matter(self) -> str:
        """Everything the document says outside a rule."""
        return "\n".join([self.preamble, *(body for _, body in self.sections)])


def split_label(text: str) -> tuple[str | None, str]:
    """A deviation carries a short title and a body. Word separates them with a line break
    inside one paragraph, which is authoritative and used when present. Flattened text loses
    that, so the fallback guesses the join, which is almost always lowercase or a closing
    bracket followed by a capital or a quote. Every check reads the whole entry, so a wrong
    guess costs presentation and never a finding."""
    if "\n" in text:
        head, _, rest = text.partition("\n")
        return head.strip() or None, rest.strip()
    m = re.search(r'(?<=[a-z)\]])(?=[A-Z"“])', text)
    if not m or m.start() < 3:
        return None, text.strip()
    return text[: m.start()].strip(), text[m.start() :].strip()


def _parse_guidance(rule: Rule) -> None:
    g = rule.guidance
    if m := _RULE_ID.search(g):
        rule.rule_id = m.group(1).rstrip(".,;")
    if m := _DEPENDS.search(g):
        for ref, why in _DEP_ITEM.findall(m.group(1)):
            if ref and ref.lower() not in {"and", "or"}:
                rule.depends_on.append((ref.rstrip(".,;"), (why or "").strip() or None))
    if m := _PRECEDENCE.search(g):
        rule.precedence = m.group(1).strip()
    if m := _EXHAUSTION.search(g):
        rule.on_exhaustion = m.group(1).strip()
    if m := _SOURCE.search(g):
        rule.source = m.group(1).strip()
        rule.reviewed = m.group(2)


def _build(blocks: list[tuple[bool, str]], name: str) -> Playbook:
    """blocks are (is_heading, text). A non-heading block is one paragraph and stays whole,
    which is what keeps a deviation's title attached to its body: flattening to lines made
    them two entries, and the title was then discarded as a parsing artefact."""
    pb = Playbook(name=name)
    current: Rule | None = None
    slot: str | None = None
    buf: list[str] = []
    in_preamble = False

    def flush() -> None:
        nonlocal buf
        body = [b.strip() for b in buf if b.strip()]
        buf = []
        if not body:
            return
        if in_preamble and current is None:
            pb.preamble += ("\n" if pb.preamble else "") + "\n".join(body)
            return
        if current is None:
            return
        if slot is None:
            current.prose.extend(body)
            return
        if slot == "standard":
            current.standard = "\n".join(body)
        elif slot in ("acceptable", "unacceptable"):
            getattr(current, slot).extend(body)
        elif slot == "guidance":
            current.guidance = "\n".join(body)
        elif slot == "workflow":
            current.workflow.extend(body)
        elif slot == "required":
            current.required = body[0].strip().lower().startswith("y")
        elif slot == "optional":
            current.required = not body[0].strip().lower().startswith("y")

    for is_heading, block in blocks:
        if not is_heading:
            buf.append(block)
            continue
        flush()
        title = block.strip()
        key = title.lower().rstrip(":")
        if key in _PREAMBLE_HEADINGS:
            current, slot, in_preamble = None, None, True
            continue
        if key in _FIELD_HEADINGS:
            slot = _FIELD_HEADINGS[key]
            continue
        # anything else at this point is a rule name
        in_preamble = False
        current = Rule(name=title, position=len(pb.rules) + 1)
        pb.rules.append(current)
        slot = None
    flush()

    # A heading with none of the five fields under it is not a rule, whatever its level: it is
    # a section of the document. Levels are unreliable across exports, the fields are not.
    real, sections = [], []
    for r in pb.rules:
        if r.has_fields:
            real.append(r)
        else:
            sections.append((r.name, "\n".join(r.prose)))
    pb.rules = real
    pb.sections = sections
    for i, r in enumerate(pb.rules, start=1):
        r.position = i
        _parse_guidance(r)
    return pb


def parse_markdown(text: str, name: str = "playbook") -> Playbook:
    """Line-based, for a .md rendering. Each line is its own block."""
    blocks: list[tuple[bool, str]] = []
    for line in text.splitlines():
        h = re.match(r"^#{1,6}\s+(.*)$", line)
        blocks.append((True, h.group(1)) if h else (False, line))
    return _build(blocks, name)


def docx_to_markdown(path: str | Path) -> str:
    """Flatten a .docx to the heading shape parse_markdown reads."""
    target = Path(path).expanduser()
    if not target.exists():
        raise PromptGraphError(f"No playbook at {target}")
    try:
        root = ET.fromstring(zipfile.ZipFile(target).read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError) as e:
        raise PromptGraphError(f"{target.name} is not a readable .docx: {e}") from e
    out: list[str] = []
    for p in root.iter(f"{W}p"):
        txt = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if not txt:
            continue
        st = p.find(f"{W}pPr/{W}pStyle")
        val = st.get(f"{W}val") if st is not None else ""
        if val and val.lower().startswith("heading"):
            depth = val[-1] if val[-1].isdigit() else "2"
            out.append(f"{'#' * int(depth)} {txt}")
        else:
            out.append(txt)
    return "\n".join(out)


def _docx_blocks(target: Path) -> list[tuple[bool, str]]:
    try:
        root = ET.fromstring(zipfile.ZipFile(target).read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError) as e:
        raise PromptGraphError(f"{target.name} is not a readable .docx: {e}") from e
    blocks: list[tuple[bool, str]] = []
    for p in root.iter(f"{W}p"):
        parts: list[str] = []
        for node in p.iter():
            tag = node.tag.replace(W, "")
            if tag == "t":
                parts.append(node.text or "")
            elif tag in ("br", "cr"):
                parts.append("\n")  # Word's intra-paragraph break: a deviation's title ends here
            elif tag == "tab":
                parts.append("\t")
        txt = "".join(parts).strip()
        if not txt:
            continue
        st = p.find(f"{W}pPr/{W}pStyle")
        val = st.get(f"{W}val") if st is not None else ""
        blocks.append((bool(val and val.lower().startswith("heading")), txt))
    return blocks


def parse_docx(path: str | Path) -> Playbook:
    target = Path(path).expanduser()
    if not target.exists():
        raise PromptGraphError(f"No playbook at {target}")
    return _build(_docx_blocks(target), name=target.stem)


# ---------------------------------------------------------------------------
# The mechanical checks. Twelve of the authoring checklist's twenty-three, being
# the ones a machine can settle without typed positions or a declared context.
# ---------------------------------------------------------------------------

_THIN_RULE_COUNT = 60

# Where the missing thing goes, in the authoring format's own terms. Never what it should say:
# the content of an unacceptable position is a judgment about a deal, and where that is the
# honest answer the remedy says so rather than inventing one.
#
# These encode a format defined in a document held elsewhere. If that document changes, they
# become confidently wrong, which is the same exposure specification freshness describes.
_REMEDY: dict[str, str] = {
    "RULE_ID_MISSING": "A dotted path on the first line of Guidance, stable across rewording.",
    "RULE_ID_DUPLICATE": "One of the two needs a different path. Whichever is already referenced elsewhere keeps the one it has.",
    "ABSENCE_REMEDIATION_MISSING": "A closing line on the standard position, with the wording supplied rather than described.",
    "NO_ACCEPTABLE_DEVIATION": "An acceptable deviation, or a deliberate record that everything here escalates.",
    "UNACCEPTABLE_NOT_STATED": "The unacceptable field. What belongs in it is a judgment about this deal.",
    "DEVIATION_UNSPECIFIED": "Name the edits that are pre-authorised, or say what 'reasonable' excludes.",
    "PROSE_SUBSTITUTES_FOR_STRUCTURE": "Consolidate the two rules into one, restate the condition against something observable in the contract, or escalate instead. Consolidation is right most often.",
    "DEPENDS_ON_UNRESOLVED": "Correct the path, or add the rule it names.",
    "DEPENDENCY_REASON_MISSING": "A reason in brackets after the path: trade-off, definition, aggregate exposure or ordering.",
    "PRECEDENCE_ONE_SIDED": "The reciprocal sentence in the other rule. Both halves are needed, because a subagent reads one rule.",
    "PARENT_CHILD_DUPLICATION": "Fold the child into the parent's fallback as numbered caveats, which also removes a subagent.",
    "PREAMBLE_RESTATES_RULE": "Remove the position from the preamble. The rule is the source of truth.",
    "LADDER_GAP": "Either the acceptable ceiling moves up or the unacceptable floor comes down to meet it. Which of the two is a judgment about this deal.",
    "DOCUMENT_CONTROL_MISSING": "A control block in the preamble: version, owner, steward, effective date, review triggers.",
    "EXHAUSTION_DEFAULT_MISSING": "A default in the preamble, with explicit paths only on the rules that differ from it.",
    "RULE_COUNT_HIGH": "Consolidate rules that split a single concept. Each rule costs a subagent at review time.",
    # diff
    "RULE_RENAMED": "Nothing, if the rename was intended. A Rule ID would make the next one a fact rather than an inference.",
    "RULE_ID_CHANGED": "Restore the former path, or update every reference to it.",
    "REFERENCE_BROKEN": "Correct the path, or add the rule it names.",
    "REFERENCE_TO_RENAMED_RULE": "Update the naming rule to the new name.",
    "RENAMED_RULE_SELF_REFERENCE": "Update the rule's own text to the name it now has.",
    "RULE_REMOVED": "Remove what still references it, or restore it.",
}


def playbook_check(pb: Playbook) -> list[Finding]:
    out: list[Finding] = []

    def f(code: str, r: Rule | None, obs: str, ev: dict[str, Any] | None = None) -> None:
        out.append(
            Finding(
                code,
                "rule" if r else "playbook",
                r.rule_id or r.position if r else None,
                r.name if r else pb.name,
                obs,
                ev or {},
                _REMEDY.get(code),
            )
        )

    ids: dict[str, Rule] = {}
    for r in pb.rules:
        if r.rule_id:
            if r.rule_id in ids:
                f(
                    "RULE_ID_DUPLICATE",
                    r,
                    f"Rule ID '{r.rule_id}' is already used by another rule.",
                    {"other": ids[r.rule_id].name},
                )
            ids[r.rule_id] = r

    for r in pb.rules:
        if not r.rule_id:
            f(
                "RULE_ID_MISSING",
                r,
                "The rule carries no Rule ID, so nothing else can reference it and a rename "
                "breaks every reference to it.",
            )

        if r.required and not r.absence_remediation:
            f(
                "ABSENCE_REMEDIATION_MISSING",
                r,
                "The rule is required but its standard position says nothing about what to do "
                "when the provision is absent.",
                {"required": True},
            )

        if not r.acceptable:
            f(
                "NO_ACCEPTABLE_DEVIATION",
                r,
                "The rule states a standard position and no acceptable deviation, so every "
                "non-conforming clause becomes a matter for a human.",
            )

        if not r.unacceptable:
            f(
                "UNACCEPTABLE_NOT_STATED",
                r,
                "The rule states no unacceptable deviation, so the space between the last "
                "acceptable position and a dealbreaker has no defined treatment.",
            )

        for entry in r.acceptable:
            _, body = split_label(entry)
            if _ONLY_REASONABLE.match(body.strip()):
                f(
                    "DEVIATION_UNSPECIFIED",
                    r,
                    "An acceptable deviation says only that reasonable edits are acceptable, "
                    "which does not say which edits.",
                    {"entry": entry[:200]},
                )

        if m := _PROSE_GATE.search(r.guidance):
            f(
                "PROSE_SUBSTITUTES_FOR_STRUCTURE",
                r,
                "Guidance states a condition in prose that the schema has no field for, so it "
                "will be read and not acted on.",
                {"phrase": m.group(1), "field": "guidance"},
            )

        for ref, why in r.depends_on:
            if ref not in ids:
                f(
                    "DEPENDS_ON_UNRESOLVED",
                    r,
                    f"The rule declares a dependency on '{ref}', which is not a Rule ID in this "
                    "playbook.",
                    {"ref": ref, "reason": why},
                )
            if not why:
                f(
                    "DEPENDENCY_REASON_MISSING",
                    r,
                    f"The dependency on '{ref}' does not say why, so a reader changing one rule "
                    "cannot tell what the other needs.",
                    {"ref": ref},
                )

    for r in pb.rules:
        if not (r.acceptable and r.unacceptable):
            continue
        acc = " ".join(r.acceptable)
        una = " ".join(r.unacceptable)
        ceiling = _BOUNDED.search(acc)
        # only fires where the two sides are measured on the same scale: a categorical pair
        # (advice of counsel against opinion of counsel) has no interval to leave open
        if ceiling and _UNBOUNDED.search(una) and not _BOUNDED.search(una):
            f(
                "LADDER_GAP",
                r,
                "The acceptable position has a finite ceiling and the only unacceptable "
                "position is unbounded, so a value between the two has no stated treatment.",
                {
                    "ceiling": ceiling.group(0).strip(),
                    "unbounded": _UNBOUNDED.search(una).group(0),
                },
            )

    # precedence is only load-bearing when both sides carry it: a subagent reads one rule
    for r in pb.rules:
        if not r.precedence:
            continue
        named = [o for o in pb.rules if o is not r and o.name.lower() in r.precedence.lower()]
        for other in named:
            if not other.precedence or r.name.lower() not in other.precedence.lower():
                f(
                    "PRECEDENCE_ONE_SIDED",
                    r,
                    f"This rule states precedence against '{other.name}', which does not state "
                    "the reciprocal, so the relationship is invisible from that side.",
                    {"other": other.name},
                )

    # a parent and its children holding the same text is two places to change one policy
    for parent in pb.rules:
        kids = [
            c
            for c in pb.rules
            if c is not parent and c.name.lower().startswith(parent.name.lower() + " ")
        ]
        if not kids:
            continue
        blob = " ".join(parent.acceptable + [parent.standard]).lower()
        for c in kids:
            body = (c.standard or "").lower()
            if body and _overlap(body, blob) >= 0.5:
                f(
                    "PARENT_CHILD_DUPLICATION",
                    c,
                    f"This rule's content also appears inside '{parent.name}', so one policy is "
                    "recorded in two places and each costs its own subagent.",
                    {"parent": parent.name, "overlap": round(_overlap(body, blob), 2)},
                )

    # "One source of truth per position." A preamble that names a rule and restates its position
    # is a second place to change when the policy moves, and the two drift apart silently
    # because nothing reads them together. Surfaced by rendering the preamble next to the rules.
    low = pb.preamble.lower()
    for r in pb.rules:
        name = r.name.lower().split(" / ")[0].strip()
        if len(name) < 6 or name not in low:
            continue
        i = low.index(name)
        window = low[i : i + 240]
        if _overlap(window, " ".join([r.standard, *r.acceptable]).lower()) >= 0.35:
            f(
                "PREAMBLE_RESTATES_RULE",
                r,
                "The preamble states a position for this rule, so the same policy is recorded "
                "in two places and a change to one will not move the other.",
                {"preamble_extract": pb.preamble[i : i + 160].strip()},
            )

    if not _DOC_CONTROL.search(pb.front_matter):
        f(
            "DOCUMENT_CONTROL_MISSING",
            None,
            "The playbook carries no document control block, so there is no way to say what "
            "policy governed a review performed on a given date.",
            {"front_matter_chars": len(pb.front_matter)},
        )

    if not re.search(r"exhaustion", pb.front_matter, re.I) and not any(
        r.on_exhaustion for r in pb.rules
    ):
        f(
            "EXHAUSTION_DEFAULT_MISSING",
            None,
            "Neither the preamble nor any rule says what happens when a fallback is also refused.",
        )

    if len(pb.rules) > _THIN_RULE_COUNT:
        f(
            "RULE_COUNT_HIGH",
            None,
            f"The playbook has {len(pb.rules)} rules, and every rule costs a subagent at review "
            "time, so thin rules covering one concept are worth consolidating.",
            {"rules": len(pb.rules), "threshold": _THIN_RULE_COUNT},
        )

    return out


def _overlap(a: str, b: str) -> float:
    """Token containment of a in b. Deliberately not Jaccard: a short child rule inside a long
    parent fallback should score high, and Jaccard would divide that away."""
    ta = {w for w in re.findall(r"[a-z0-9]+", a) if len(w) > 3}
    tb = {w for w in re.findall(r"[a-z0-9]+", b) if len(w) > 3}
    return len(ta & tb) / len(ta) if ta else 0.0


# ---------------------------------------------------------------------------
# Rename detection. Harvey keys rules by name, and the conventions reference rules by id or by
# name in prose, so a rename silently breaks every reference pointing at the old one. Nothing in
# the platform detects that. This compares two exports rather than requiring a stored history,
# because the question an author has mid-revision is what the edit just broke.
# ---------------------------------------------------------------------------

_RENAME_THRESHOLD = 0.6

# Word substitutes curly punctuation on save, so the same rule name round-trips as a different
# string. Reporting that as a rename is noise, and worse, it buries the real renames in a list
# of typography. Names are compared with punctuation folded; the displayed name is untouched.
_PUNCT = str.maketrans(
    {
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)


def _norm_name(name: str) -> str:
    return " ".join(name.translate(_PUNCT).lower().split())


def _jaccard(a: str, b: str) -> float:
    ta = {w for w in re.findall(r"[a-z0-9]+", a.lower()) if len(w) > 3}
    tb = {w for w in re.findall(r"[a-z0-9]+", b.lower()) if len(w) > 3}
    return len(ta & tb) / len(ta | tb) if (ta or tb) else 0.0


def _body(r: Rule) -> str:
    return " ".join([r.standard, *r.acceptable, *r.unacceptable])


def _pair(
    before: Playbook, after: Playbook
) -> tuple[list[tuple[Rule, Rule]], list[tuple[Rule, Rule, float]], list[Rule], list[Rule]]:
    """Match rules across two versions: by id, then by name, then by content for the remainder.

    The third pass exists because rule ids are a convention nobody has adopted yet. Where ids
    are present the match is exact and a rename is a fact; where they are absent it is inferred
    from content and reported with its score, never as a certainty."""
    b_left, a_left = list(before.rules), list(after.rules)
    matched: list[tuple[Rule, Rule]] = []

    by_id = {r.rule_id: r for r in a_left if r.rule_id}
    for b in list(b_left):
        if b.rule_id and b.rule_id in by_id:
            a = by_id.pop(b.rule_id)
            matched.append((b, a))
            b_left.remove(b)
            a_left.remove(a)

    by_name = {_norm_name(r.name): r for r in a_left}
    for b in list(b_left):
        if (a := by_name.pop(_norm_name(b.name), None)) is not None:
            matched.append((b, a))
            b_left.remove(b)
            a_left.remove(a)

    renamed: list[tuple[Rule, Rule, float]] = []
    for b in list(b_left):
        best, score = None, 0.0
        for a in a_left:
            s = _jaccard(_body(b), _body(a))
            if s > score:
                best, score = a, s
        if best is not None and score >= _RENAME_THRESHOLD:
            renamed.append((b, best, score))
            b_left.remove(b)
            a_left.remove(best)
    return matched, renamed, b_left, a_left


def _references(pb: Playbook) -> list[tuple[Rule, str, str]]:
    """Every outward reference a rule makes: (rule, kind, target). Dependencies point at ids,
    precedence points at names, because that is how each convention is written."""
    out: list[tuple[Rule, str, str]] = []
    for r in pb.rules:
        for ref, _ in r.depends_on:
            out.append((r, "depends_on", ref))
        if r.precedence:
            for other in pb.rules:
                if other is not r and other.name.lower() in r.precedence.lower():
                    out.append((r, "precedence", other.name))
    return out


def playbook_diff(before: Playbook, after: Playbook) -> dict[str, Any]:
    matched, renamed, removed, added = _pair(before, after)
    findings: list[Finding] = []

    def f(code: str, name: str, obs: str, ev: dict[str, Any]) -> None:
        findings.append(Finding(code, "rule", ev.get("rule_id"), name, obs, ev, _REMEDY.get(code)))

    for b, a, score in renamed:
        f(
            "RULE_RENAMED",
            a.name,
            f"'{b.name}' appears to have been renamed to '{a.name}'. Rules are keyed by name, "
            "so any reference to the old name no longer resolves.",
            {"from": b.name, "to": a.name, "match": round(score, 2), "by": "content"},
        )
    for b, a in matched:
        if _norm_name(b.name) != _norm_name(a.name):
            f(
                "RULE_RENAMED",
                a.name,
                f"'{b.name}' was renamed to '{a.name}', identified by a stable Rule ID.",
                {"from": b.name, "to": a.name, "by": "rule_id", "rule_id": a.rule_id},
            )
        if b.rule_id and a.rule_id and b.rule_id != a.rule_id:
            f(
                "RULE_ID_CHANGED",
                a.name,
                f"The Rule ID changed from '{b.rule_id}' to '{a.rule_id}', which breaks every "
                "reference to the old one.",
                {"from": b.rule_id, "to": a.rule_id, "rule_id": a.rule_id},
            )

    # what the edit broke: references in the new document that no longer resolve
    old_names = {_norm_name(r.name) for r in before.rules}
    new_names = {_norm_name(r.name) for r in after.rules}
    new_ids = {r.rule_id for r in after.rules if r.rule_id}
    renamed_from = {_norm_name(b.name): a.name for b, a, _ in renamed}
    renamed_from |= {
        _norm_name(b.name): a.name for b, a in matched if _norm_name(b.name) != _norm_name(a.name)
    }

    for r, kind, target in _references(after):
        if kind == "depends_on" and target not in new_ids:
            f(
                "REFERENCE_BROKEN",
                r.name,
                f"'{r.name}' depends on '{target}', which is not a Rule ID in this version.",
                {"kind": kind, "target": target, "rule_id": r.rule_id},
            )

    # a reference to a name that existed before and does not now. A rule still using its own
    # former name is a different defect from a rule pointing at another one, and conflating them
    # sends a reader looking for a cross-reference that was never there.
    renamed_to = {_norm_name(a.name): _norm_name(b.name) for b, a, _ in renamed}
    renamed_to |= {
        _norm_name(a.name): _norm_name(b.name)
        for b, a in matched
        if _norm_name(b.name) != _norm_name(a.name)
    }
    for r in after.rules:
        text = " ".join(filter(None, [r.precedence, r.guidance]))
        for gone in old_names - new_names:
            if not gone or gone not in text.lower():
                continue
            if renamed_to.get(_norm_name(r.name)) == gone:
                f(
                    "RENAMED_RULE_SELF_REFERENCE",
                    r.name,
                    f"'{r.name}' was renamed but its own text still calls it '{gone}'.",
                    {"former_name": gone, "rule_id": r.rule_id},
                )
            else:
                f(
                    "REFERENCE_TO_RENAMED_RULE",
                    r.name,
                    f"'{r.name}' still names '{gone}', which no longer exists under that name"
                    + (f" (now '{renamed_from[gone]}')" if gone in renamed_from else "")
                    + ".",
                    {"names": gone, "now": renamed_from.get(gone), "rule_id": r.rule_id},
                )

    for b in removed:
        still = [
            r.name for r in after.rules if _norm_name(b.name) in _norm_name(r.precedence or "")
        ]
        f(
            "RULE_REMOVED",
            b.name,
            f"'{b.name}' is no longer in the playbook."
            + (f" Still referenced by {len(still)} rule(s)." if still else ""),
            {"referenced_by": still, "rule_id": b.rule_id},
        )

    changed = [
        (b, a)
        for b, a in matched
        if _body(b) != _body(a) or b.guidance != a.guidance or b.required != a.required
    ]
    return {
        "before": before.name,
        "after": after.name,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "renamed": len(renamed)
            + sum(1 for b, a in matched if _norm_name(b.name) != _norm_name(a.name)),
            "changed": len(changed),
            "unchanged": len(matched) - len(changed),
        },
        "added": [r.name for r in added],
        "removed": [r.name for r in removed],
        "renamed": [{"from": b.name, "to": a.name, "match": round(s, 2)} for b, a, s in renamed],
        "changed": [a.name for _, a in changed],
        "finding_count": len(findings),
        "findings": findings,
    }
