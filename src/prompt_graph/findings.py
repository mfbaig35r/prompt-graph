"""The one output shape every tool shares.

A finding is a factual observation. It never contains a severity adjective or a suggested
rewrite; Claude supplies the interpretation in the skill's voice.

`remedy` is the one narrow exception and was added deliberately. Where a check knows the
authoring format, it can say *where* the missing thing goes and *in what shape* without saying
what it should contain: "a dotted path on the first line of Guidance" is a fact about the
format, not advice about a deal. A remedy never drafts a position, and where the honest answer
is that a person decides, it says so. Most findings have none.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Finding:
    code: str
    subject_type: str  # matter | standard | table | column | prompt | parameter | binding | run | eval | assertion | dependency
    subject_id: int | str | None
    subject_name: str
    observation: str  # one factual sentence
    evidence: dict[str, Any] = field(default_factory=dict)
    # where the missing thing goes, never what it should say. See the module docstring.
    remedy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def dump(findings: list[Finding]) -> list[dict[str, Any]]:
    return [f.to_dict() for f in findings]


class PromptGraphError(Exception):
    """Raised for input the server cannot act on (unknown matter, malformed record).

    The message is written for the model, which explains it to the user.
    """
