"""The one output shape every tool shares.

A finding is a factual observation. It never contains advice, a severity adjective, or a
suggested rewrite; Claude supplies the interpretation in the skill's voice.
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def dump(findings: list[Finding]) -> list[dict[str, Any]]:
    return [f.to_dict() for f in findings]


class PromptGraphError(Exception):
    """Raised for input the server cannot act on (unknown matter, malformed record).

    The message is written for the model, which explains it to the user.
    """
