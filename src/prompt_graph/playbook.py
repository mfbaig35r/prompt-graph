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

# Prose standing in for structure. These are the openings the authoring format names.
_PROSE_GATE = re.compile(
    r"(this rule applies only when|only applies when|applies only if|"
    r"unless the client has|where we have already agreed|see the rule on|"
    r"has been accepted with client approval)",
    re.I,
)

# An entry that says nothing but "reasonable edits".
_ONLY_REASONABLE = re.compile(r"^(?:ok to\s+)?(?:accept|allow)?\s*reasonable edits?\.?$", re.I)

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

    # parsed out of guidance, per the authoring conventions
    rule_id: str | None = None
    depends_on: list[tuple[str, str | None]] = field(default_factory=list)
    precedence: str | None = None
    on_exhaustion: str | None = None
    source: str | None = None
    reviewed: str | None = None

    @property
    def absence_remediation(self) -> bool:
        """States what to do when the provision is missing, and supplies the wording."""
        return bool(_ABSENCE.search(self.standard) and _OPERATIVE.search(self.standard))


@dataclass(slots=True)
class Playbook:
    name: str
    preamble: str = ""
    rules: list[Rule] = field(default_factory=list)


def _split_label(text: str) -> tuple[str | None, str]:
    """Harvey's export concatenates a deviation's title to its body with no separator, in one
    run, so formatting cannot recover the boundary. The join is almost always lowercase or a
    closing bracket followed by a capital or a quote. The split is cosmetic: every check reads
    the whole string, so a wrong guess costs presentation and never a verdict."""
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


def parse_markdown(text: str, name: str = "playbook") -> Playbook:
    """Parse the heading shape the Word export renders. Levels are ignored; the heading text
    decides what a block is, because export depth has varied between documents."""
    pb = Playbook(name=name)
    current: Rule | None = None
    slot: str | None = None
    buf: list[str] = []
    in_preamble = False

    def flush() -> None:
        nonlocal buf
        body = [ln.strip() for ln in buf if ln.strip()]
        buf = []
        if not body:
            return
        if in_preamble and current is None:
            pb.preamble += ("\n" if pb.preamble else "") + "\n".join(body)
            return
        if current is None or slot is None:
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

    for line in text.splitlines():
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not h:
            buf.append(line)
            continue
        flush()
        title = h.group(2).strip()
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

    for r in pb.rules:
        _parse_guidance(r)
        r.acceptable = [_split_label(x)[1] or x for x in r.acceptable]
        r.unacceptable = [_split_label(x)[1] or x for x in r.unacceptable]
    return pb


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


def parse_docx(path: str | Path) -> Playbook:
    target = Path(path).expanduser()
    return parse_markdown(docx_to_markdown(target), name=target.stem)


# ---------------------------------------------------------------------------
# The mechanical checks. Twelve of the authoring checklist's twenty-three, being
# the ones a machine can settle without typed positions or a declared context.
# ---------------------------------------------------------------------------

_THIN_RULE_COUNT = 60


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
            _, body = _split_label(entry)
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

    if not _DOC_CONTROL.search(pb.preamble):
        f(
            "DOCUMENT_CONTROL_MISSING",
            None,
            "The playbook carries no document control block, so there is no way to say what "
            "policy governed a review performed on a given date.",
            {"preamble_chars": len(pb.preamble)},
        )

    if not re.search(r"exhaustion", pb.preamble, re.I) and not any(
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
