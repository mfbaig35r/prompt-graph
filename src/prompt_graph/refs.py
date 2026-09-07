"""Parsing Harvey `@Column Name` references out of prompt text.

Harvey column names contain spaces, so an `@` reference has no syntactic terminator. The
parser resolves each `@` against the known column names of the table (longest match wins,
case-insensitive), and only falls back to a heuristic token when nothing matches, so the
unresolved name reported to the user is what they most likely typed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Words that commonly follow a reference inline and are never part of a column name we accept.
_STOP_WORDS = {
    "is",
    "are",
    "was",
    "were",
    "and",
    "or",
    "when",
    "to",
    "for",
    "in",
    "with",
    "as",
    "the",
    "equals",
    "of",
    "if",
    "then",
    "returns",
    "return",
    "result",
    "value",
    "column",
    "on",
    "at",
    "by",
    "from",
    "that",
    "this",
    "a",
    "an",
    "not",
    "unless",
    "where",
    "so",
    "but",
    "has",
    "have",
}

_AT = re.compile(r"(?<![\w@.])@(?=[A-Za-z\[])")


@dataclass(slots=True)
class Ref:
    raw: str  # what appears after '@' as best we can tell
    resolved_name: str | None  # canonical column name when resolved
    offset: int


def _heuristic_token(text: str, start: int) -> str:
    """Take words after '@' until a delimiter or a stop word; used only when unresolved."""
    end = len(text)
    m = re.compile(r"[\n`,.;:()\[\]\"']").search(text, start)
    if m:
        end = m.start()
    segment = text[start:end]
    words = segment.split()
    kept: list[str] = []
    for w in words:
        if w.lower() in _STOP_WORDS and kept:
            break
        kept.append(w)
        if len(kept) >= 6:
            break
    return " ".join(kept).strip()


def find_refs(text: str, known_names: list[str]) -> list[Ref]:
    """Return every `@` reference in `text`, resolved against `known_names` where possible."""
    names_sorted = sorted(known_names, key=len, reverse=True)
    lowered = [(n, n.lower()) for n in names_sorted]
    refs: list[Ref] = []
    for m in _AT.finditer(text):
        start = m.end()
        window = text[start : start + 200]
        window_l = window.lower()
        hit: str | None = None
        for canonical, low in lowered:
            if window_l.startswith(low):
                after = window[len(low) : len(low) + 1]
                # A name match must end at a word boundary so `@Date` does not match `@Dates`.
                if after == "" or not (after.isalnum() or after == "_"):
                    hit = canonical
                    break
        if hit is not None:
            refs.append(Ref(raw=window[: len(hit)], resolved_name=hit, offset=start))
        else:
            tok = _heuristic_token(text, start)
            if tok:
                refs.append(Ref(raw=tok, resolved_name=None, offset=start))
    return refs


def referenced_names(text: str, known_names: list[str]) -> tuple[list[str], list[str]]:
    """(resolved canonical names, unresolved raw tokens), each de-duplicated in order."""
    resolved: list[str] = []
    unresolved: list[str] = []
    for r in find_refs(text, known_names):
        if r.resolved_name is not None:
            if r.resolved_name not in resolved:
                resolved.append(r.resolved_name)
        elif r.raw not in unresolved:
            unresolved.append(r.raw)
    return resolved, unresolved
