"""prompt-graph MCP server: stdio transport, name-addressed tools, findings not verdicts.

Every tool docstring is written for the model calling it. The server never drafts or
rewrites prompt text, never parses files, and never makes a legal determination.
"""

from __future__ import annotations

import argparse
import functools
import os
import sqlite3
import sys
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, BeforeValidator, Field

from . import checks as checks_mod
from . import (
    coverage,
    db,
    evaluation,
    export,
    freshness,
    graph,
    lint,
    overview,
    parameters,
    readiness,
    service,
)
from .constants import COVERAGE_DIMENSION_KEYS, FALLBACK_VOCABULARY, NATIVE_TYPE_ALIASES
from .findings import Finding, PromptGraphError, dump
from .models import (
    ColumnRecord,
    ConsumerBinding,
    EntityRecord,
    EvalRecord,
    SectionRecord,
    TableMeta,
    fold,
)

INSTRUCTIONS = """Prompt Graph stores, versions, validates, and computes over the Harvey review-table
prompts of an M&A diligence matter. It never drafts or rewrites prompt text (the
legal-review-table-builder skill does that), never parses files (read the export and submit
normalized records), and never makes legal determinations.

Tools return findings: {code, subject_type, subject_id, subject_name, observation, evidence}.
An observation is one factual sentence. Interpret it for the user in the skill's voice.
Every matter, table, column, and parameter is addressed by name. Ids in results exist so you
can pass them back to tools (run_id to eval_record or run_compare, for example); never show
an id or raw JSON to the user unless they ask.

Typical session: matter_open → table_ingest (per table) → parameter_set (shared entities such
as the target's legal name) → suite_check → impact_of_change before any rerun →
run_record + eval_record after a Harvey run → failures_summary / run_compare →
memo_outline_set + coverage_check before diligence begins."""

mcp = FastMCP("prompt-graph", instructions=INSTRUCTIONS)

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = db.connect()
    return _conn


def set_conn(conn: sqlite3.Connection | None) -> None:
    """Used by tests to point the tools at an in-memory database."""
    global _conn
    _conn = conn


def _finish(result: dict[str, Any]) -> dict[str, Any]:
    """Serialise Finding objects and add a count so the model can lead with it."""
    out = dict(result)
    fs = out.get("findings")
    if fs is not None and fs and isinstance(fs[0], Finding):
        out["findings"] = dump(fs)
    out.setdefault("findings", [])
    out["finding_count"] = len(out["findings"])
    return out


def _tool(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return _finish(fn(*args, **kwargs))
        except PromptGraphError as e:
            return {"error": str(e), "findings": [], "finding_count": 0}

    return wrapper


# ---------------------------------------------------------------------------
# Parameter types: closed sets are enums (case-folded on the way in), every scalar has a
# description the model can read. Fields inside batch models stay soft so one bad record
# never rejects a whole batch; see DECISIONS.md.
# ---------------------------------------------------------------------------


def _native(v: Any) -> Any:
    return NATIVE_TYPE_ALIASES.get(v.strip().lower(), v.strip()) if isinstance(v, str) else v


class ConceptTarget(BaseModel):
    table: str
    column: str


Matter = Annotated[str, Field(description="Matter name, as the user says it (case-insensitive).")]
Table = Annotated[str, Field(description="Review table name within the matter.")]
Column = Annotated[str, Field(description="Column name within the table.")]
Actor = Annotated[
    str | None,
    Field(
        description="Who is doing this, for the change log: a name or role such as 'J. Doe' "
        "or 'paralegal'. Optional; not authenticated."
    ),
]
NativeType = Annotated[
    Literal["Classify", "Date", "Currency", "Number", "Duration", "Verbatim", "FreeResponse"],
    BeforeValidator(_native),
    Field(
        description="Harvey column type. 'Free Response', 'text', and lower-case spellings are accepted."
    ),
]
Status = Annotated[
    Literal["draft", "testing", "verified", "retired"],
    BeforeValidator(fold),
    Field(description="Column lifecycle status."),
]
Role = Annotated[
    Literal["orientation", "extraction", "validation", "reconciliation", "human_review"],
    BeforeValidator(fold),
    Field(description="Stage in the skill's staged design pattern."),
]
Bump = Annotated[
    Literal["minor", "major"],
    BeforeValidator(fold),
    Field(
        description="Version increment: minor (v1.1) for a revision, major (v2.0) for a redesign."
    ),
]
Side = Annotated[
    Literal["buy", "sell"],
    BeforeValidator(fold),
    Field(description="Which side of the transaction the review is on."),
]
Scope = Annotated[
    Literal["firm", "matter"],
    BeforeValidator(fold),
    Field(
        description="'firm' for the baseline every matter inherits; 'matter' for one matter's overlay."
    ),
]
SourceType = Annotated[
    Literal["chat", "excel", "csv", "harvey_export", "drafted"],
    BeforeValidator(fold),
    Field(description="Where the records came from, recorded as provenance."),
]
GroupBy = Annotated[
    Literal["class", "table", "column"],
    BeforeValidator(fold),
    Field(description="How to group the open failures."),
]
ParamStatus = Annotated[
    Literal["unresolved", "resolved", "contested"],
    BeforeValidator(fold),
    Field(
        description="Resolution status. Defaults to resolved when a value is given, else unresolved."
    ),
]


def _optional(inner: Any, description: str) -> Any:
    """`X | None` with the description on the outer field, where every client reads it."""
    return Annotated[inner | None, Field(description=description)]


SideOpt = _optional(Side, "Which side of the transaction the review is on.")
StatusOpt = _optional(Status, "Column lifecycle status.")
RoleOpt = _optional(Role, "Stage in the skill's staged design pattern.")
NativeTypeOpt = _optional(
    NativeType,
    "Harvey column type. 'Free Response', 'text', and lower-case spellings are accepted.",
)
ParamStatusOpt = _optional(
    ParamStatus, "Resolution status. Defaults to resolved when a value is given, else unresolved."
)

CheckFamily = Annotated[
    Literal["prompts", "graph", "parameters", "consistency"],
    BeforeValidator(fold),
]
CoverageDimension = Annotated[
    Literal[*COVERAGE_DIMENSION_KEYS],  # type: ignore[valid-type]
    BeforeValidator(
        lambda v: fold(v).replace("-", "_").replace(" ", "_") if isinstance(v, str) else v
    ),
]
ChangeNote = Annotated[
    str | None, Field(description="One line saying what changed and why, for the change log.")
]


# ---------------------------------------------------------------------------
# Matter and standard
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def matter_open(
    name: Annotated[
        str | None,
        Field(description="Matter name. Omit it to list the matters that exist."),
    ] = None,
    create: Annotated[
        bool,
        Field(
            description="Create the matter if no matter has this name. Default false, so a typo lists the real matters instead of creating a phantom."
        ),
    ] = False,
    objective: Annotated[
        str | None, Field(description="One or two sentences on the review objective.")
    ] = None,
    side: SideOpt = None,
    vault_project_id: Annotated[
        str | None,
        Field(
            description="Harvey Vault project id the matter's tables run against, for document-set freshness. Tables can override it."
        ),
    ] = None,
    actor: Actor = None,
) -> dict[str, Any]:
    """Open a matter and return its full suite-level state, or list the matters that exist.

    Call this first in a session, and again whenever the user asks where things stand.
    With no name it returns the list of matters. With a name it returns every table with
    column counts by status, Table Instructions version, last run, staleness counts
    (never_run / current / direct / transitive), open failures, shared parameters with
    their resolution status, the memo outline if one is stored, and the effective standard.
    An unknown name returns an error listing the matters that do exist; pass create=true to
    start a new one.
    """
    conn = get_conn()
    if name is None or not name.strip():
        matters = service.list_matters(conn)
        return {
            "matters": [
                {
                    "name": m["name"],
                    "side": m["side"],
                    "status": m["status"],
                    "created_at": m["created_at"],
                }
                for m in matters
            ],
            "count": len(matters),
            "findings": [],
        }
    m, created = service.matter_open(
        conn,
        name,
        create=create,
        objective=objective,
        side=side,
        actor=actor,
        vault_project_id=vault_project_id,
    )
    out = overview.matter_overview(conn, m)
    out["created"] = created
    out["findings"] = []
    return out


@mcp.tool()
@_tool
def standard_set(
    scope: Scope,
    matter: Annotated[
        str | None, Field(description="Matter name; required when scope is 'matter'.")
    ] = None,
    fallback_vocabulary: Annotated[
        list[str] | None,
        Field(
            description="The controlled fallback states. Seeded from the skill; changing it is reported."
        ),
    ] = None,
    naming_rules: Annotated[
        str | None, Field(description="The exact-name rule for entities and individuals.")
    ] = None,
    date_pattern: Annotated[
        str | None, Field(description="Date format every prompt uses, e.g. YYYY-MM-DD.")
    ] = None,
    currency_pattern: Annotated[
        str | None, Field(description="Currency format every prompt uses, e.g. 'USD 1,000.00'.")
    ] = None,
    default_evidence_boundary: Annotated[
        str | None,
        Field(
            description="What a column may look at unless it says otherwise, e.g. 'current review unit only'."
        ),
    ] = None,
    entities: Annotated[
        list[EntityRecord] | None,
        Field(
            description="Review-subject entities with exact legal names, and named non-subjects such as the buyer."
        ),
    ] = None,
    objective: Annotated[
        str | None, Field(description="The matter's review objective, for the overlay.")
    ] = None,
    conventions: Annotated[
        list[str] | None, Field(description="Matter-specific conventions, one sentence each.")
    ] = None,
    change_note: ChangeNote = None,
    actor: Actor = None,
) -> dict[str, Any]:
    """Define or amend the firm baseline or a matter overlay.

    Fields you omit carry forward from the previous version. A matter overlay may add the
    review-subject entities, the objective, and matter conventions. It may not contradict
    the firm baseline's fallback vocabulary, date pattern, currency pattern, or evidence
    boundary: an attempted contradiction is stored but reported as STANDARD_CONTRADICTS_FIRM
    and the firm value stays effective. Returns the effective merged standard.
    """
    return service.standard_set(
        get_conn(),
        scope,
        matter,
        fallback_vocabulary,
        naming_rules,
        date_pattern,
        currency_pattern,
        default_evidence_boundary,
        entities,
        objective,
        conventions,
        change_note,
        actor,
    )


# ---------------------------------------------------------------------------
# Ingest and revision
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def table_ingest(
    matter: Matter,
    table: Table,
    columns: Annotated[
        list[ColumnRecord],
        Field(description="One normalized record per column, in table order."),
    ],
    table_meta: Annotated[
        TableMeta | None,
        Field(
            description="What one row is, whether grouping is used, the table's stage and position."
        ),
    ] = None,
    table_instructions: Annotated[
        str | None,
        Field(
            description="The table's Table Instructions text, exactly as entered in Harvey. Exports omit them; pass them whenever you have them."
        ),
    ] = None,
    source_type: SourceType = "chat",
    change_note: ChangeNote = None,
    actor: Actor = None,
) -> dict[str, Any]:
    """Store a review table and its column prompts as normalized records you have extracted.

    Read the export, workbook, or pasted prompts yourself and submit one record per column.
    Re-ingesting an existing table is safe: columns are matched by name; a changed prompt
    gets a new minor version, an unchanged one is left alone, a new name creates a column,
    and a stored column missing from the submission is reported (COLUMN_ABSENT_FROM_INGEST),
    never retired silently. A rename must be done with column_revise. Every @Column
    reference is resolved; unresolved ones are reported. A record with no usable native
    type is skipped and reported; the rest of the batch is stored. Each stored prompt is
    linted (see prompt_check).
    """
    return service.table_ingest(
        get_conn(),
        matter,
        table,
        columns,
        table_meta,
        table_instructions,
        source_type,
        actor,
        change_note,
    )


@mcp.tool()
@_tool
def table_instructions_set(
    matter: Matter,
    table: Table,
    text: Annotated[
        str, Field(description="The full Table Instructions text, exactly as entered in Harvey.")
    ],
    change_note: ChangeNote = None,
    source_type: SourceType = "chat",
    actor: Actor = None,
) -> dict[str, Any]:
    """Store a new version of a table's Table Instructions (the corpus-wide shared rules).

    Identical text is not versioned again. A change makes every column in the table stale
    until it is rerun. Reports INSTRUCTIONS_VOCABULARY_INCOMPLETE when the text does not
    list all five controlled fallback states.
    """
    return service.table_instructions_set(
        get_conn(), matter, table, text, change_note, source_type, actor
    )


@mcp.tool()
@_tool
def column_revise(
    matter: Matter,
    table: Table,
    column: Column,
    prompt_text: Annotated[
        str | None,
        Field(description="The revised prompt, in full. Unchanged text creates no version."),
    ] = None,
    change_note: ChangeNote = None,
    failure_class_addressed: Annotated[
        str | None,
        Field(
            description="The skill failure class this revision fixes, e.g. scope_leakage or 'Evidence overstatement'."
        ),
    ] = None,
    status: StatusOpt = None,
    rename_to: Annotated[
        str | None,
        Field(
            description="New column name. The only way to rename; prompts still using the old @name are reported, not rewritten."
        ),
    ] = None,
    purpose: Annotated[
        str | None,
        Field(description="One attorney-readable sentence on what the column is for."),
    ] = None,
    role: RoleOpt = None,
    concept: Annotated[
        str | None,
        Field(
            description="Short tag for the legal concept extracted, e.g. 'formation date', for cross-table comparison."
        ),
    ] = None,
    native_type: NativeTypeOpt = None,
    configured_options: Annotated[
        list[str] | None, Field(description="Classify only: the configured options in UI order.")
    ] = None,
    bump: Bump = "minor",
    actor: Actor = None,
) -> dict[str, Any]:
    """Record a revision to one column: a new prompt version, a rename, a status change, or metadata.

    Use it after the skill has drafted a revised prompt: pass prompt_text with a change_note
    and the failure_class_addressed so the change log reads like the inventory template.
    Retiring a column reports every column that still depends on it. Downstream columns
    become stale automatically; call impact_of_change for the rerun scope.
    """
    return service.column_revise(
        get_conn(),
        matter,
        table,
        column,
        prompt_text,
        change_note,
        failure_class_addressed,
        status,
        rename_to,
        purpose,
        role,
        concept,
        native_type,
        configured_options,
        bump,
        None,
        actor,
    )


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def column_read(
    matter: Matter,
    table: Table,
    column: Column,
    include_history: Annotated[
        bool, Field(description="Also return every prior prompt version and the change log.")
    ] = False,
) -> dict[str, Any]:
    """Read one column in full: current prompt text, type, options, purpose, upstream and
    downstream dependencies (with kind and table), parameters it consumes or sources,
    staleness with reasons, and evaluation summary.
    """
    return {
        **service.column_read(get_conn(), matter, table, column, include_history),
        "findings": [],
    }


@mcp.tool()
@_tool
def columns_find(
    matter: Matter,
    table: Annotated[str | None, Field(description="Limit to one table.")] = None,
    native_type: NativeTypeOpt = None,
    status: StatusOpt = None,
    failure_class: Annotated[
        str | None,
        Field(description="Columns with an open failure of this skill failure class."),
    ] = None,
    consumes_parameter: Annotated[
        str | None,
        Field(
            description="Columns bound to this shared parameter, directly or through their table's instructions."
        ),
    ] = None,
    stale: Annotated[
        bool | None,
        Field(
            description="true for directly or transitively stale columns only; false for current ones only."
        ),
    ] = None,
    name_contains: Annotated[
        str | None, Field(description="Case-insensitive substring of the column name.")
    ] = None,
    role: RoleOpt = None,
    concept: Annotated[str | None, Field(description="Exact concept tag.")] = None,
    limit: Annotated[int, Field(description="Maximum columns to return.", ge=1, le=500)] = 100,
    offset: Annotated[int, Field(description="Skip this many matches, for paging.", ge=0)] = 0,
) -> dict[str, Any]:
    """Find columns across the matter by filter; returns summaries, not prompt text.

    Filters combine. The result carries total and truncated; page with offset when
    truncated is true. Use column_read for the full text of one column.
    """
    return {
        **service.columns_find(
            get_conn(),
            matter,
            table,
            native_type,
            status,
            failure_class,
            consumes_parameter,
            stale,
            name_contains,
            role,
            concept,
            limit=limit,
            offset=offset,
        ),
        "findings": [],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def concept_set(
    matter: Matter,
    concept: Annotated[
        str | None,
        Field(
            description="The shared concept, e.g. 'documents in unit'. Pass null to clear the tag."
        ),
    ] = None,
    names: Annotated[
        list[str] | None,
        Field(
            description="Tag every active column with these names, across every table. This is "
            "how a reported cluster of similar names is accepted in one call."
        ),
    ] = None,
    columns: Annotated[
        list[ConceptTarget] | None,
        Field(description="Specific columns, when only some of a cluster belongs together."),
    ] = None,
    actor: Actor = None,
) -> dict[str, Any]:
    """Tag columns with a shared concept, so cross-table comparison is a fact rather than a guess.

    Consistency reports similar column names by token overlap because nothing says whether they
    are the same concept. This records the answer. Once tagged, a cluster leaves the heuristic
    and enters the explicit path, where divergent names, types or fallback states are still
    reported, now confirmed rather than inferred. Tagging confirms a finding; renaming the
    columns is what resolves it.

    To dismiss a false positive, give each side its own concept: both leave the heuristic and
    neither groups with the other. Say what you tagged and why, and run suite_check after.
    """
    return service.concept_set(
        get_conn(),
        matter,
        concept,
        names,
        [c.model_dump() for c in columns] if columns else None,
        actor,
    )


@mcp.tool()
@_tool
def prompt_check(
    prompt_text: Annotated[str, Field(description="The draft prompt, in full.")],
    native_type: NativeType,
    configured_options: Annotated[
        list[str] | None, Field(description="Classify only: the configured options in UI order.")
    ] = None,
    matter: Annotated[
        str | None,
        Field(
            description="With table, lets @Column references be resolved against stored columns."
        ),
    ] = None,
    table: Annotated[str | None, Field(description="The table this draft belongs to.")] = None,
    column_name: Annotated[
        str | None,
        Field(
            description="The column this draft is for, if it exists, so self- and forward references are checked."
        ),
    ] = None,
    column_position: Annotated[
        int | None,
        Field(
            description="1-based position the column will have, for forward-reference checks on a new column."
        ),
    ] = None,
) -> dict[str, Any]:
    """Lint a draft prompt before storing it. Deterministic; no judgment about legal content.

    Rules: character count (hard fail above 10,000, advisory above 6,000); fallback
    vocabulary (only `Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`,
    `Unable to determine`; synonyms N/A, None, Unclear, Silent, Unknown, TBD are reported);
    `Not stated` outside Date/Number/Currency/Duration or `Not addressed` inside one; Classify
    labels absent from configured_options and em-dash qualifiers in Classify; unresolved or
    forward @Column references (when matter and table are given); missing output contract;
    Markdown permitted in the cell without an output contract allowing it; a rule expressed
    as a character count; an @Column declared in the preamble that no rule then uses (dead
    reference).
    """
    conn = get_conn()
    cols: list[tuple[str, int]] | None = None
    if matter and table:
        m = service.get_matter(conn, matter)
        t = service.get_table(conn, int(m["id"]), table)
        cols = [
            (c["name"], int(c["position"]))
            for c in service.table_columns(conn, int(t["id"]), include_retired=True)
        ]
        if column_name and column_position is None:
            try:
                column_position = int(
                    service.get_column(conn, int(t["id"]), column_name)["position"]
                )
            except PromptGraphError:
                column_position = None
    ctx = lint.PromptContext(native_type, configured_options, column_name, column_position, cols)
    fs = lint.check_prompt(prompt_text, ctx, subject_name=column_name or "draft")
    return {
        "char_count": len(prompt_text),
        "native_type": native_type,
        "references_checked": cols is not None,
        "fallback_terms_used": lint.fallback_terms_used(prompt_text),
        "vocabulary": list(FALLBACK_VOCABULARY),
        "findings": fs,
    }


@mcp.tool()
@_tool
def suite_check(
    matter: Matter,
    checks: Annotated[
        list[CheckFamily] | None, Field(description="Families to run; all by default.")
    ] = None,
    table: Annotated[str | None, Field(description="Limit to one table.")] = None,
) -> dict[str, Any]:
    """Check the whole suite for structural and consistency problems. Returns findings only.

    Families: 'graph' (dependency cycles, unresolved or forward @Column references, ordering
    against the skill's staged pattern, a narrative column acting as control plane for
    several dependents, dependencies on retired columns); 'parameters' (orphaned parameters,
    unresolved parameters with consumers, a consuming table that never binds the value into
    its Table Instructions, resolved values absent from the bound text, dangling bindings);
    'consistency' (date and currency pattern drift against the standard, an entity printed
    differently from the matter standard's exact name, the same concept extracted under
    different names or with different types/options/fallbacks across tables, missing or
    incomplete Table Instructions); 'prompts' (the prompt_check rules over every stored
    prompt).
    """
    return checks_mod.suite_check(get_conn(), matter, list(checks) if checks else None, table)


# ---------------------------------------------------------------------------
# Graph and staleness
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def impact_of_change(
    matter: Matter,
    table: Annotated[
        str | None, Field(description="With column: the table of the column that changed.")
    ] = None,
    column: Annotated[str | None, Field(description="The column that changed.")] = None,
    parameter: Annotated[
        str | None,
        Field(description="Instead of a column: the shared parameter that changed."),
    ] = None,
    new_value: Annotated[
        str | None,
        Field(
            description="The value the parameter is about to take, echoed in the result for the user."
        ),
    ] = None,
) -> dict[str, Any]:
    """Everything downstream of a column or a shared parameter, across tables, in rerun order.

    Give table+column, or parameter. Each affected column is marked 'direct' (depends on the
    subject itself) or 'transitive', with the dependency kind that carries it
    (intra_table_ref = a real Harvey @Column; cross_table_parameter = via a shared
    parameter; advisory = a dependency Harvey cannot express). For a parameter the result
    also lists every consumer binding and every Table Instructions or prompt that contains
    the current value and would need editing (the server does not edit text). Cycle-safe;
    a cycle is reported as a GRAPH_CYCLE finding.
    """
    conn = get_conn()
    m = service.get_matter(conn, matter)
    if parameter:
        p = service.get_parameter(conn, int(m["id"]), parameter)
        return graph.impact_of_parameter(conn, int(m["id"]), p, new_value)
    if not (table and column):
        raise PromptGraphError("Give table and column, or a parameter name.")
    t = service.get_table(conn, int(m["id"]), table)
    c = service.get_column(conn, int(t["id"]), column)
    return graph.impact_of_column(conn, int(m["id"]), int(c["id"]))


@mcp.tool()
@_tool
def staleness_report(
    matter: Matter,
    table: Annotated[str | None, Field(description="Limit to one table.")] = None,
) -> dict[str, Any]:
    """Which columns need a rerun and why, across the matter or for one table.

    'direct': the column's own prompt, its table's instructions, or a bound parameter changed
    after its last run. 'transitive': an upstream column (any dependency kind, any table) is
    stale or changed after this column's last run. 'never_run': no run recorded. Includes a
    dependency-ordered rerun sequence for the stale set.
    """
    conn = get_conn()
    m = service.get_matter(conn, matter)
    tid = int(service.get_table(conn, int(m["id"]), table)["id"]) if table else None
    return {
        "matter": m["name"],
        "table": table,
        **graph.staleness_report(conn, int(m["id"]), tid),
    }


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def parameter_set(
    matter: Matter,
    name: Annotated[str, Field(description="Parameter name, e.g. 'Target Legal Name'.")],
    value: Annotated[
        str | None,
        Field(
            description="The resolved value, e.g. 'Harbor Logistics Holdings, LLC'. A changed value marks every consumer stale."
        ),
    ] = None,
    source_table: Annotated[
        str | None, Field(description="Table whose column resolves this value.")
    ] = None,
    source_column: Annotated[
        str | None,
        Field(
            description="Column that resolves this value, e.g. the entity table's Principal Entity."
        ),
    ] = None,
    consumers: Annotated[
        list[ConsumerBinding] | None,
        Field(
            description="Tables or columns that use the value, and whether it sits in their Table Instructions or one prompt."
        ),
    ] = None,
    replace_consumers: Annotated[
        bool, Field(description="Replace the existing bindings instead of adding to them.")
    ] = False,
    status: ParamStatusOpt = None,
    note: Annotated[
        str | None, Field(description="Free text, e.g. why the value is contested.")
    ] = None,
    actor: Actor = None,
) -> dict[str, Any]:
    """Declare, resolve, or rebind a shared parameter: the cross-table dependency mechanism.

    Harvey's @Column reference stops at the table boundary; a shared parameter bound to its
    consumers is the only place a cross-table dependency exists, and it is what
    impact_of_change and staleness_report read. Reports bindings whose text does not
    contain the value.
    """
    return parameters.parameter_set(
        get_conn(),
        matter,
        name,
        value,
        source_table,
        source_column,
        consumers,
        replace_consumers,
        status,
        note,
        actor,
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def run_record(
    matter: Matter,
    table: Table,
    started_at: Annotated[
        str | None,
        Field(description="ISO 8601 date or datetime the run started; defaults to now."),
    ] = None,
    note: Annotated[
        str | None,
        Field(description="What this run was, e.g. 'first full run on the 14-document set'."),
    ] = None,
    evaluator: Annotated[str | None, Field(description="Who evaluated the results.")] = None,
    corpus_note: Annotated[
        str | None, Field(description="Size, source, and date of the test corpus.")
    ] = None,
    columns: Annotated[
        list[str] | None,
        Field(
            description="Only these columns were rerun (a selective rerun). Default: every active column."
        ),
    ] = None,
    coverage_dimensions: Annotated[
        list[CoverageDimension] | None,
        Field(
            description="Test-set dimensions from the skill's evaluation log that the corpus covered. Tick only what was actually tested."
        ),
    ] = None,
    documents_ready: Annotated[
        int | None,
        Field(
            description="How many documents were in the vault and ready when the run started; records a manual document-set snapshot for freshness.",
            ge=0,
        ),
    ] = None,
    documents_as_of: Annotated[
        str | None,
        Field(
            description="ISO 8601 time the document count was observed; defaults to the run start."
        ),
    ] = None,
    actor: Actor = None,
) -> dict[str, Any]:
    """Record that a table was run in Harvey, snapshotting the prompt version of each column
    and the document set it ran against.

    Staleness is computed against the prompt snapshot, freshness against the document-set
    snapshot, so record a run before logging results. If documents_ready is omitted, the
    latest snapshot for the table's vault project is linked (from freshness_check). Tick only
    the coverage dimensions the corpus actually covered; an unticked dimension is treated as
    open risk by coverage_check.
    """
    return evaluation.run_record(
        get_conn(),
        matter,
        table,
        started_at,
        note,
        evaluator,
        corpus_note,
        columns,
        coverage_dimensions,
        actor,
        documents_ready,
        documents_as_of,
    )


@mcp.tool()
@_tool
def eval_record(
    matter: Matter,
    table: Table,
    results: Annotated[
        list[EvalRecord],
        Field(description="One record per (column, test document); passes as well as failures."),
    ],
    run_id: Annotated[
        int | None,
        Field(description="The run these results belong to; defaults to the table's latest run."),
    ] = None,
    actor: Actor = None,
) -> dict[str, Any]:
    """Log evaluation results for a run, one record per (column, test document), in batch.

    Fields mirror the skill's evaluation-log-template.csv. failure_class is one of the
    skill's failure classes in snake_case (e.g. scope_leakage; the label spelling
    'Scope leakage' is also accepted); error_type is substantive | evidentiary |
    formatting. Every record is stored; a problem with one is reported as a finding that
    lists the accepted values, never dropped. A failure stays open until a later result for
    the same column and document passes.
    """
    return evaluation.eval_record(get_conn(), matter, table, results, run_id, actor)


@mcp.tool()
@_tool
def failures_summary(
    matter: Matter,
    table: Annotated[str | None, Field(description="Limit to one table.")] = None,
    group_by: GroupBy = "class",
) -> dict[str, Any]:
    """Open failures grouped by class, table, or column, to surface systematic problems.

    An open failure is a (column, document) pair whose latest result failed. Reports
    FAILURE_CLASS_RECURRING when one class is open on three or more columns or in more than
    one table.
    """
    return evaluation.failures_summary(get_conn(), matter, table, group_by)


@mcp.tool()
@_tool
def run_compare(
    matter: Matter,
    table: Table,
    run_a: Annotated[
        int | None,
        Field(description="The earlier run. Omit both ids to compare the two latest runs."),
    ] = None,
    run_b: Annotated[int | None, Field(description="The later run.")] = None,
    column: Annotated[str | None, Field(description="Limit to one column.")] = None,
) -> dict[str, Any]:
    """Compare two runs of a table over the same test documents: fixed, still failing, newly
    failing (regressions), plus documents present in only one run.
    """
    return evaluation.run_compare(get_conn(), matter, table, run_a, run_b, column)


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def memo_outline_set(
    matter: Matter,
    sections: Annotated[
        list[SectionRecord],
        Field(description="The memo's sections, each with the assertions it must be able to make."),
    ],
    name: Annotated[str, Field(description="Name of the deliverable.")] = "Diligence memo",
    actor: Actor = None,
) -> dict[str, Any]:
    """Store the deliverable's outline: sections, and under each the assertions the memo must make.

    Each assertion needs kind='extraction' (document evidence a column can supply; map it to
    the columns with sources=[{table, column}]) or kind='judgment' (a determination the
    attorney makes: which document is operative, whether a defect exists, whether consent is
    required or properly obtained, materiality, enforceability, deal consequence; sources here
    are the evidence inputs the attorney will consult). Never label a judgment as extraction:
    coverage_check would then report it as a gap to be fixed by a column. Replaces the
    previous outline version.
    """
    return coverage.memo_outline_set(get_conn(), matter, sections, name, actor)


@mcp.tool()
@_tool
def coverage_check(matter: Matter) -> dict[str, Any]:
    """The sufficiency test: can the table suite support the memo? Returns a gap report.

    Per assertion: reliably_covered (at least one source column has a run, no open failure,
    is not stale, and its table ticks every applicable test dimension); nominally_covered
    (sourced, but every source has an open failure, an unticked dimension, no run, or is
    stale); extraction_gap (an extraction assertion with no active source column: a schema
    defect); judgment_boundary (an attorney determination: correct behaviour, not a defect).
    Also lists unsourced columns (columns feeding no assertion) and tables with unticked
    dimensions. Before any run every sourced assertion is nominal; say so rather than
    reading it as failure.
    """
    return coverage.coverage_check(get_conn(), matter)


# ---------------------------------------------------------------------------
# Freshness, readiness, export (Addendum A)
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def freshness_check(
    matter: Matter,
    table: Annotated[
        str | None,
        Field(
            description="Limit to one table (and, with refresh, observe only its vault project)."
        ),
    ] = None,
    refresh: Annotated[
        bool,
        Field(
            description="Observe the vault now: from the Harvey Vault API when HARVEY_API_KEY is configured, or from the manual count given here."
        ),
    ] = False,
    ready_count: Annotated[
        int | None,
        Field(
            description="Manual observation: how many documents are ready in the vault right now.",
            ge=0,
        ),
    ] = None,
    as_of: Annotated[
        str | None, Field(description="ISO 8601 time of the manual observation; defaults to now.")
    ] = None,
    latest_uploaded_at: Annotated[
        str | None,
        Field(description="Manual observation: upload time of the newest document, if known."),
    ] = None,
    file_ids: Annotated[
        list[str] | None,
        Field(
            description="Manual observation: the ready file ids, if you have them; lets additions and removals be counted exactly."
        ),
    ] = None,
    vault_project_id: Annotated[
        str | None,
        Field(description="Observe this vault project instead of the one on the table or matter."),
    ] = None,
    note: Annotated[
        str | None, Field(description="Where the manual observation came from.")
    ] = None,
    force: Annotated[
        bool, Field(description="Poll the API even if it was polled in the last five minutes.")
    ] = False,
    actor: Actor = None,
) -> dict[str, Any]:
    """Has the document set moved since each table last ran? Source freshness, alongside staleness.

    A column can be verified, not stale, and passing while being wrong because the vault
    grew since it ran. Per table: 'moved' (documents added or removed since the last run,
    with the counts), 'current', 'unrecorded' (the last run has no document-set snapshot),
    'never_run', or 'unobserved' (no snapshot at all). With refresh=true a new snapshot is
    taken first: from the Harvey Vault API (10 requests a minute per organisation, so a
    poll inside five minutes returns the cached snapshot unless force=true) or from a
    manual count. Findings carry the observation's provenance; a manual count is a weaker
    claim than an API enumeration. Ends with the memo assertions whose sources ran against
    a moved set. Whether the new documents matter is the attorney's call.
    """
    return freshness.freshness_check(
        get_conn(),
        matter,
        table,
        refresh,
        ready_count,
        as_of,
        latest_uploaded_at,
        file_ids,
        vault_project_id,
        note,
        force,
        actor,
    )


@mcp.tool()
@_tool
def table_readiness(matter: Matter, table: Table) -> dict[str, Any]:
    """Is this table ready to run against the real vault? One call, findings grouped by cause.

    Composes: prompt lint on every column; graph, parameter, and consistency checks scoped
    to the table; unresolved shared parameters the table consumes; columns still draft or
    testing, stale, or never run; open failures from the latest results; unticked test-set
    dimensions; document-set freshness. Returns counts by cause and no verdict: readiness
    against a live client matter is a judgment, and this makes sure nothing is missed.
    """
    return readiness.table_readiness(get_conn(), matter, table)


@mcp.tool()
@_tool
def matter_export(
    matter: Matter,
    write_to: Annotated[
        str | None,
        Field(
            description="File or directory to write the JSON to. Default: an 'exports' folder beside the database."
        ),
    ] = None,
    inline: Annotated[
        bool,
        Field(description="Return the document in the result instead of writing a file. Large."),
    ] = False,
) -> dict[str, Any]:
    """Serialise the whole matter to one versioned JSON document: a record of how the diligence
    was conducted.

    Contains the standard in effect, every table and its Table Instructions versions, every
    column with full prompt history, the dependency graph, shared parameters and bindings,
    every run with its prompt-version and document-set snapshots, all evaluation results,
    the memo outline and coverage state, and the provenance log. Useful at closing, on
    handoff, on a lateral departure, in any later question about what was reviewed and when,
    and as disaster recovery for the database file. Returns the path and counts.
    """
    return export.matter_export(get_conn(), matter, write_to, inline)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="prompt-graph", description="Prompt Graph MCP server (stdio)."
    )
    parser.add_argument("--db", help=f"SQLite path (default: ${db.ENV_VAR} or {db.DEFAULT_PATH})")
    parser.add_argument(
        "--seed-demo", action="store_true", help="Load the Project Harbor demo matter and exit."
    )
    parser.add_argument("--migrate", action="store_true", help="Apply migrations and exit.")
    args = parser.parse_args(argv)
    if args.db:
        os.environ[db.ENV_VAR] = args.db
    if args.migrate:
        conn = db.connect()
        print(f"schema version {db.current_version(conn)} at {db.db_path()}", file=sys.stderr)
        return
    if args.seed_demo:
        from .seed import load_demo

        conn = db.connect()
        summary = load_demo(conn)
        print(
            f"seeded '{summary['matter']}' with {summary['tables']} tables at {db.db_path()}",
            file=sys.stderr,
        )
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
