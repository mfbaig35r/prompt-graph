"""Deterministic prompt lint (requirements §8, prompt-level rules).

Every rule here is a mechanical restatement of an instruction in the skill. The rules are
lexical: they look at what the prompt tells Harvey to return, not at whether the prompt is
good. Where a rule is a heuristic over free text, the docstring says so and DECISIONS.md
records the choice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .constants import (
    CHAR_LIMIT_ADVISORY,
    CHAR_LIMIT_HARD,
    FALLBACK_SYNONYMS,
    FALLBACK_VOCABULARY,
    QUALIFIER_TERMS,
    TYPED_COLUMNS,
)
from .findings import Finding
from .refs import find_refs

_BACKTICK = re.compile(r"`([^`\n]{1,120})`")
_RETURN_PHRASE = re.compile(
    r"\breturn(?:s|ed)?(?:\s+(?:exactly|only|the\s+value|the\s+label))?\s+[\"'“]?([^`\n\"'”.;,]{1,80})",
    re.IGNORECASE,
)
_NEGATED_LINE = re.compile(
    r"\b(do not|don't|never|not use|must not|should not|instead of|rather than|no longer)\b",
    re.IGNORECASE,
)
_OUTPUT_HEADING = re.compile(
    r"^\s{0,3}#{1,4}\s*(output|response\s+format|cell\s+output|format\s+of\s+the\s+answer)",
    re.IGNORECASE | re.MULTILINE,
)
_HEADING = re.compile(r"^\s{0,3}#{1,4}\s*(.+?)\s*$", re.MULTILINE)
_RETURN_INSTRUCTION = re.compile(r"\breturn\b", re.IGNORECASE)
_MARKDOWN_TERMS = re.compile(
    r"\b(markdown|bullet(?:ed|s)?(?:\s+list)?|bold|italic|heading(?:s)?|table\s+format|"
    r"markdown\s+table|numbered\s+list)\b",
    re.IGNORECASE,
)
_MARKDOWN_ALLOW = re.compile(
    r"\b(markdown|bullet(?:ed|s)?(?:\s+list)?|bold|italic|heading(?:s)?)\b", re.IGNORECASE
)
_PLAIN_TEXT = re.compile(
    r"\b(plain\s+text|no\s+markdown|without\s+markdown|not\s+use\s+markdown)\b", re.IGNORECASE
)
_EM_DASH_QUALIFIER = re.compile(
    r"(Unable to determine|Incorporated terms)\s*[—–]\s*\S", re.IGNORECASE
)
_CHAR_COUNT_RULE = re.compile(r"\b\d[\d,]*\s*(?:characters?|chars?)\b", re.IGNORECASE)
_ESTABLISHED_HEADING = re.compile(r"established\s+results?|upstream\s+results?", re.IGNORECASE)
_GENERIC_UPSTREAM_USE = re.compile(
    r"\b(?:established|upstream)\s+(?:results?|values?|states?|classifications?)\b", re.IGNORECASE
)
_QUALIFIER_PHRASE = re.compile(
    r"\b(qualifier|after an em dash|followed by a (?:short|brief) (?:reason|explanation|qualifier))\b",
    re.IGNORECASE,
)
_PATTERN_TOKENS = re.compile(
    r"^(YYYY|MM|DD|USD|EUR|GBP|\$|[0-9,.\-/ ]+|\[.*\]|/s/|[a-z].*)", re.IGNORECASE
)


@dataclass(slots=True)
class PromptContext:
    native_type: str
    configured_options: list[str] | None = None
    column_name: str | None = None
    column_position: int | None = None
    table_columns: list[tuple[str, int]] | None = None  # (name, position) of every column


def _lines_with(text: str, needle: str) -> list[str]:
    low = needle.lower()
    return [ln.strip() for ln in text.splitlines() if low in ln.lower()]


def _candidate_output_tokens(text: str) -> list[str]:
    """Tokens the prompt presents as something Harvey returns: backticked, or after 'return'."""
    tokens: list[str] = []
    for m in _BACKTICK.finditer(text):
        tokens.append(m.group(1).strip())
    for m in _RETURN_PHRASE.finditer(text):
        tokens.append(m.group(1).strip())
    return tokens


def _sections(text: str) -> dict[str, str]:
    """Split on Markdown headings; keys are lower-cased heading text, '' is the preamble."""
    out: dict[str, str] = {}
    positions = [(m.start(), m.end(), m.group(1).strip().lower()) for m in _HEADING.finditer(text)]
    if not positions:
        return {"": text}
    out[""] = text[: positions[0][0]]
    for i, (_start, end, name) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        out[name] = text[end:nxt]
    return out


def _term_used_positively(text: str, term: str) -> list[str]:
    """Lines where `term` appears as an output token and the line is not a prohibition."""
    hits: list[str] = []
    term_l = term.lower()
    for ln in text.splitlines():
        low = ln.lower()
        if term_l not in low:
            continue
        in_backticks = any(t.strip().lower() == term_l for t in _BACKTICK.findall(ln))
        in_return = any(t.strip().lower() == term_l for t in _RETURN_PHRASE.findall(ln))
        if not (in_backticks or in_return):
            continue
        if _NEGATED_LINE.search(ln):
            continue
        hits.append(ln.strip())
    return hits


def check_prompt(text: str, ctx: PromptContext, subject_name: str = "draft") -> list[Finding]:
    findings: list[Finding] = []
    sid = ctx.column_name or subject_name
    n = len(text)

    # --- character limits ---
    if n > CHAR_LIMIT_HARD:
        findings.append(
            Finding(
                "PROMPT_LENGTH_HARD",
                "prompt",
                None,
                sid,
                f"The prompt is {n:,} characters, above the {CHAR_LIMIT_HARD:,}-character Harvey limit.",
                {"char_count": n, "limit": CHAR_LIMIT_HARD},
            )
        )
    elif n > CHAR_LIMIT_ADVISORY:
        findings.append(
            Finding(
                "PROMPT_LENGTH_ADVISORY",
                "prompt",
                None,
                sid,
                f"The prompt is {n:,} characters, above the {CHAR_LIMIT_ADVISORY:,}-character target the skill sets.",
                {"char_count": n, "target": CHAR_LIMIT_ADVISORY},
            )
        )

    # --- fallback synonyms ---
    for syn in FALLBACK_SYNONYMS:
        lines = _term_used_positively(text, syn)
        if lines:
            findings.append(
                Finding(
                    "FALLBACK_SYNONYM",
                    "prompt",
                    None,
                    sid,
                    f"The prompt presents `{syn}` as a returnable value, which is not in the controlled fallback vocabulary.",
                    {"term": syn, "lines": lines[:5], "vocabulary": list(FALLBACK_VOCABULARY)},
                )
            )

    # --- Not stated / Not addressed by column type ---
    typed = ctx.native_type in TYPED_COLUMNS
    if not typed:
        lines = _term_used_positively(text, "Not stated")
        if lines:
            findings.append(
                Finding(
                    "FALLBACK_NOT_STATED_UNTYPED",
                    "prompt",
                    None,
                    sid,
                    f"`Not stated` is presented as a returnable value in a {ctx.native_type} column; the skill reserves it for Date, Number, Currency, and Duration columns.",
                    {"native_type": ctx.native_type, "lines": lines[:5]},
                )
            )
    else:
        lines = _term_used_positively(text, "Not addressed")
        if lines:
            findings.append(
                Finding(
                    "FALLBACK_NOT_ADDRESSED_TYPED",
                    "prompt",
                    None,
                    sid,
                    f"`Not addressed` is presented as a returnable value in a {ctx.native_type} column, where the skill's silence state is `Not stated`.",
                    {"native_type": ctx.native_type, "lines": lines[:5]},
                )
            )

    # --- Classify rules ---
    if ctx.native_type == "Classify":
        options = [o.strip() for o in (ctx.configured_options or [])]
        opt_l = {o.lower() for o in options}
        vocab_l = {v.lower() for v in FALLBACK_VOCABULARY}
        known_cols = {c[0].lower() for c in (ctx.table_columns or [])}
        unknown: list[str] = []
        for tok in _candidate_output_tokens(text):
            t = tok.strip().strip("“”\"'")
            if not t or "@" in t:
                continue
            if t.lower() in opt_l or t.lower() in vocab_l or t.lower() in known_cols:
                continue
            if not t[0].isupper():
                continue  # lower-case tokens are almost always phrases or patterns, not labels
            if _PATTERN_TOKENS.match(t) and not t[0].isalpha():
                continue
            if len(t) > 60:
                continue
            if t not in unknown:
                unknown.append(t)
        # Do not flag configured options that merely appear in the prompt; flag labels that do not.
        if unknown:
            findings.append(
                Finding(
                    "CLASSIFY_LABEL_NOT_CONFIGURED",
                    "prompt",
                    None,
                    sid,
                    "The prompt presents output labels that are not in the configured option set.",
                    {"labels": unknown[:12], "configured_options": options},
                )
            )
        if _EM_DASH_QUALIFIER.search(text) or _QUALIFIER_PHRASE.search(text):
            m = _EM_DASH_QUALIFIER.search(text) or _QUALIFIER_PHRASE.search(text)
            findings.append(
                Finding(
                    "CLASSIFY_QUALIFIER_PERMITTED",
                    "prompt",
                    None,
                    sid,
                    "The prompt permits a qualifier after a fallback state in a Classify column, where only the exact configured option is valid.",
                    {"match": m.group(0) if m else None, "qualifier_terms": list(QUALIFIER_TERMS)},
                )
            )
        if not options:
            findings.append(
                Finding(
                    "OPTIONS_MISSING",
                    "column",
                    None,
                    sid,
                    "This Classify column has no configured option set recorded.",
                    {},
                )
            )

    # --- @Column references ---
    if ctx.table_columns is not None:
        names = [c[0] for c in ctx.table_columns]
        pos_by_name = {c[0].lower(): c[1] for c in ctx.table_columns}
        seen_unresolved: list[str] = []
        seen_forward: list[str] = []
        for ref in find_refs(text, names):
            if ref.resolved_name is None:
                if ref.raw not in seen_unresolved:
                    seen_unresolved.append(ref.raw)
                continue
            if ctx.column_name and ref.resolved_name.lower() == ctx.column_name.lower():
                findings.append(
                    Finding(
                        "REF_SELF",
                        "prompt",
                        None,
                        sid,
                        f"The prompt references its own column `@{ref.resolved_name}`.",
                        {"reference": ref.resolved_name},
                    )
                )
                continue
            if ctx.column_position is not None:
                up_pos = pos_by_name.get(ref.resolved_name.lower())
                if up_pos is not None and up_pos > ctx.column_position:
                    if ref.resolved_name not in seen_forward:
                        seen_forward.append(ref.resolved_name)
        for raw in seen_unresolved:
            findings.append(
                Finding(
                    "REF_UNRESOLVED",
                    "prompt",
                    None,
                    sid,
                    f"The reference `@{raw}` does not match any column in the table.",
                    {"reference": raw, "table_columns": names},
                )
            )
        for nm in seen_forward:
            findings.append(
                Finding(
                    "REF_FORWARD",
                    "prompt",
                    None,
                    sid,
                    f"The prompt references `@{nm}`, which is positioned after this column in the table.",
                    {
                        "reference": nm,
                        "referenced_position": pos_by_name[nm.lower()],
                        "this_position": ctx.column_position,
                    },
                )
            )

    # --- output contract ---
    has_heading = bool(_OUTPUT_HEADING.search(text))
    has_return = bool(_RETURN_INSTRUCTION.search(text))
    if not has_heading and not has_return:
        findings.append(
            Finding(
                "OUTPUT_CONTRACT_MISSING",
                "prompt",
                None,
                sid,
                "The prompt has no output-format section and no instruction stating what to return.",
                {},
            )
        )

    # --- Markdown in cell ---
    secs = _sections(text)
    output_secs = {k: v for k, v in secs.items() if _OUTPUT_HEADING.match("## " + k)}
    output_text = "\n".join(output_secs.values())
    output_allows_md = bool(_MARKDOWN_ALLOW.search(output_text)) and not _PLAIN_TEXT.search(
        output_text
    )
    permissive_lines: list[str] = []
    for k, body in secs.items():
        if k in output_secs:
            continue
        for ln in body.splitlines():
            if (
                _MARKDOWN_TERMS.search(ln)
                and not _NEGATED_LINE.search(ln)
                and not _PLAIN_TEXT.search(ln)
            ):
                # Only lines about the answer, not about the prompt's own structure.
                if re.search(r"\b(answer|response|cell|output|return|format)\b", ln, re.IGNORECASE):
                    permissive_lines.append(ln.strip())
    if permissive_lines and not output_allows_md:
        findings.append(
            Finding(
                "MARKDOWN_IN_CELL",
                "prompt",
                None,
                sid,
                "The prompt permits Markdown in the returned answer outside an output contract that allows it.",
                {"lines": permissive_lines[:5], "has_output_section": bool(output_secs)},
            )
        )

    # --- character-count rules (the skill: models count characters unreliably) ---
    count_lines = [
        ln.strip()
        for ln in text.splitlines()
        if _CHAR_COUNT_RULE.search(ln) and not _NEGATED_LINE.search(ln)
    ]
    if count_lines:
        findings.append(
            Finding(
                "CHARACTER_COUNT_RULE",
                "prompt",
                None,
                sid,
                "The prompt contains a rule expressed as a character count, which the skill says language models apply unreliably.",
                {"lines": count_lines[:5]},
            )
        )

    # --- dead references: an @Column declared but consumed by no rule ---
    if ctx.table_columns is not None:
        established_secs = {k for k in secs if _ESTABLISHED_HEADING.search(k)}
        body_outside = "\n".join(f"{k}\n{v}" for k, v in secs.items() if k not in established_secs)
        # A line of the form "- Label: @Name" declares an input; it does not use it.
        decl_line = re.compile(r"^\s*-\s*[^:\n]{1,80}:\s*@[^\n]+$")
        use_text = "\n".join(ln for ln in body_outside.splitlines() if not decl_line.match(ln))
        generic_use = bool(_GENERIC_UPSTREAM_USE.search(use_text))
        declared = [
            r.resolved_name
            for r in find_refs(text, [c[0] for c in ctx.table_columns])
            if r.resolved_name is not None
            and not (ctx.column_name and r.resolved_name.lower() == ctx.column_name.lower())
        ]
        dead: list[str] = []
        for name in dict.fromkeys(declared):
            if generic_use:
                continue
            if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", use_text, re.IGNORECASE):
                continue
            dead.append(name)
        for name in dead:
            findings.append(
                Finding(
                    "DEAD_REFERENCE",
                    "prompt",
                    None,
                    sid,
                    f"The prompt declares `@{name}` as an input but no rule outside the established-results preamble mentions it.",
                    {"reference": name},
                )
            )

    return findings


def fallback_terms_used(text: str) -> list[str]:
    """Which controlled fallback terms the prompt presents as returnable (for consistency checks)."""
    return [t for t in FALLBACK_VOCABULARY if _term_used_positively(text, t)]
