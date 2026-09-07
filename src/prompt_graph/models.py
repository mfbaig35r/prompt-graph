"""Structured inputs Claude submits. The server never parses files; it receives these."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from .constants import NATIVE_TYPE_ALIASES


class ColumnRecord(BaseModel):
    """One normalized column, as described in requirements §5."""

    name: str = Field(description="Exact column name as it appears in Harvey.")
    position: int = Field(description="1-based order of the column within the table.")
    native_type: str | None = Field(
        default=None,
        description="Classify | Date | Currency | Number | Duration | Verbatim | FreeResponse. "
        "Leave empty if the source does not say; the server reports it.",
    )
    prompt_text: str = Field(description="The full prompt text exactly as entered in Harvey.")
    configured_options: list[str] | None = Field(
        default=None, description="Classify only: the configured options in UI order."
    )
    purpose: str | None = Field(default=None, description="One attorney-readable sentence.")
    upstream_refs: list[str] | None = Field(
        default=None,
        description="@Column names the prompt relies on, as written, if known. "
        "The server also detects them from the prompt text.",
    )
    status: str | None = Field(
        default=None,
        description="draft | testing | verified | retired. Default draft for new columns.",
    )
    role: str | None = Field(
        default=None,
        description="Optional stage in the skill's staged design: orientation | extraction | "
        "validation | reconciliation | human_review.",
    )
    concept: str | None = Field(
        default=None,
        description="Optional short tag for the legal concept extracted (e.g. 'formation date'), "
        "so the same concept can be compared across tables.",
    )
    advisory_upstream: list[AdvisoryRef] | None = Field(
        default=None,
        description="Real analytical dependencies Harvey cannot express, on columns in other tables.",
    )

    @field_validator("native_type", mode="before")
    @classmethod
    def _norm_type(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            key = v.strip().lower()
            return NATIVE_TYPE_ALIASES.get(key, v.strip())
        return v


class AdvisoryRef(BaseModel):
    table: str = Field(description="Name of the table holding the upstream column.")
    column: str = Field(description="Name of the upstream column.")
    note: str | None = None


class TableMeta(BaseModel):
    review_unit: str | None = Field(
        default=None, description="What one row represents, e.g. 'one document' or 'one entity'."
    )
    platform: str = "harvey"
    grouping_enabled: bool = False
    max_docs_per_unit: int | None = None
    stage: str | None = Field(default=None, description="Free-text lifecycle stage of the table.")
    position: int | None = Field(default=None, description="Order of the table within the matter.")


class EntityRecord(BaseModel):
    name: str = Field(description="Exact legal name.")
    jurisdiction: str | None = None
    role: str | None = Field(default=None, description="e.g. parent, subsidiary, buyer, lender.")
    is_subject: bool = Field(
        default=True, description="False for named non-subjects (buyer, lenders)."
    )


class ConsumerBinding(BaseModel):
    table: str = Field(description="Consuming table name.")
    column: str | None = Field(
        default=None, description="Consuming column name when the binding is inside one prompt."
    )
    site: str = Field(
        default="table_instructions",
        description="table_instructions | column_prompt — where the value is bound.",
    )


class EvalRecord(BaseModel):
    """One row of the skill's evaluation log (assets/evaluation-log-template.csv)."""

    column: str = Field(description="Column name.")
    test_document: str
    passed: bool
    prompt_version: str | None = Field(
        default=None, description="e.g. v1.2. Defaults to the version in the run snapshot."
    )
    actual_answer: str | None = None
    evidence_relied_on: str | None = None
    expected_behavior: str | None = None
    failure_class: str | None = Field(
        default=None, description="One of the skill's failure classes; blank for a pass."
    )
    error_type: str | None = Field(
        default=None, description="substantive | evidentiary | formatting"
    )
    revision_note: str | None = None
    rerun_scope: str | None = None
    result_after_rerun: str | None = None
    regressions: str | None = None


class AssertionRecord(BaseModel):
    text: str = Field(description="What the memo must be able to say.")
    kind: str = Field(
        description="extraction — document evidence a column can supply; "
        "judgment — a determination the attorney makes (operative document, validity, "
        "consent required, enforceability, materiality, deal consequence)."
    )
    sources: list[SourceRef] | None = Field(
        default=None,
        description="Columns that supply the evidence (extraction) or the inputs the attorney "
        "will consult (judgment).",
    )
    note: str | None = None


class SourceRef(BaseModel):
    table: str
    column: str
    note: str | None = None


class SectionRecord(BaseModel):
    name: str
    assertions: list[AssertionRecord]


ColumnRecord.model_rebuild()
AssertionRecord.model_rebuild()
