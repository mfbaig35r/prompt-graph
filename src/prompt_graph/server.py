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
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import checks as checks_mod
from . import coverage, db, evaluation, graph, lint, overview, parameters, service
from .constants import FALLBACK_VOCABULARY, NATIVE_TYPE_ALIASES, NATIVE_TYPES
from .findings import Finding, PromptGraphError, dump
from .models import (
    ColumnRecord,
    ConsumerBinding,
    EntityRecord,
    EvalRecord,
    SectionRecord,
    TableMeta,
)

INSTRUCTIONS = """Prompt Graph stores, versions, validates, and computes over the Harvey review-table
prompts of an M&A diligence matter. It never drafts or rewrites prompt text (the
legal-review-table-builder skill does that), never parses files (read the export and submit
normalized records), and never makes legal determinations.

Tools return findings: {code, subject_type, subject_id, subject_name, observation, evidence}.
An observation is one factual sentence. Interpret it for the user in the skill's voice; do
not show raw JSON or internal ids unless asked.

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


def set_conn(conn: sqlite3.Connection) -> None:
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
# Matter and standard
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def matter_open(
    name: str,
    create: bool = True,
    objective: str | None = None,
    side: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Open a matter (creating it if needed) and return its full suite-level state.

    Call this first in a session, and again whenever the user asks where things stand.
    Returns every table with column counts by status, Table Instructions version, last run,
    staleness counts (never_run / current / direct / transitive), open failures, shared
    parameters with their resolution status, the memo outline if one is stored, and the
    effective standard. `side` is 'buy' or 'sell'. With create=false an unknown name
    returns an error listing the matters that do exist.
    """
    conn = get_conn()
    m, created = service.matter_open(
        conn, name, create=create, objective=objective, side=side, actor=actor
    )
    out = overview.matter_overview(conn, m)
    out["created"] = created
    out["findings"] = []
    return out


@mcp.tool()
@_tool
def standard_set(
    scope: str,
    matter: str | None = None,
    fallback_vocabulary: list[str] | None = None,
    naming_rules: str | None = None,
    date_pattern: str | None = None,
    currency_pattern: str | None = None,
    default_evidence_boundary: str | None = None,
    entities: list[EntityRecord] | None = None,
    objective: str | None = None,
    conventions: list[str] | None = None,
    change_note: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Define or amend the firm baseline (scope='firm') or a matter overlay (scope='matter').

    Fields you omit carry forward from the previous version. A matter overlay may add the
    review-subject entities (exact legal names, jurisdictions, roles, and which are NOT
    subjects), the objective, and matter conventions. It may not contradict the firm
    baseline's fallback vocabulary, date pattern, currency pattern, or evidence boundary:
    an attempted contradiction is stored but reported as a STANDARD_CONTRADICTS_FIRM finding
    and the firm value stays effective. The firm vocabulary is seeded from the skill; changing
    it is reported as STANDARD_VOCABULARY_NOT_SKILL. Returns the effective merged standard.
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
    matter: str,
    table: str,
    columns: list[ColumnRecord],
    table_meta: TableMeta | None = None,
    table_instructions: str | None = None,
    source_type: str = "chat",
    change_note: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Store a review table and its column prompts as normalized records you have extracted.

    Read the Excel/CSV/Harvey export or the pasted prompts yourself and submit one record
    per column: name, position (1-based), native_type (Classify | Date | Currency | Number |
    Duration | Verbatim | FreeResponse), prompt_text, configured_options (Classify only, in UI
    order), and optionally purpose, upstream_refs, status, role, concept, advisory_upstream.
    Pass the Table Instructions too when you have them; exports omit them and this store is
    authoritative. source_type is 'chat', 'excel', 'csv', 'harvey_export', or 'drafted'.

    Re-ingesting an existing table is safe: columns are matched by name; a changed prompt
    gets a new minor version, an unchanged one is left alone, a new name creates a column,
    and a stored column missing from the submission is reported (COLUMN_ABSENT_FROM_INGEST),
    never retired silently. A rename must be done with column_revise. Every @Column reference
    is resolved; unresolved ones are reported. Each stored prompt is linted (see prompt_check).
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
    matter: str,
    table: str,
    text: str,
    change_note: str | None = None,
    source_type: str = "chat",
    actor: str | None = None,
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
    matter: str,
    table: str,
    column: str,
    prompt_text: str | None = None,
    change_note: str | None = None,
    failure_class_addressed: str | None = None,
    status: str | None = None,
    rename_to: str | None = None,
    purpose: str | None = None,
    role: str | None = None,
    concept: str | None = None,
    native_type: str | None = None,
    configured_options: list[str] | None = None,
    bump: str = "minor",
    actor: str | None = None,
) -> dict[str, Any]:
    """Record a revision to one column: a new prompt version, a rename, a status change, or metadata.

    Use it after the skill has drafted a revised prompt: pass prompt_text with a change_note
    and the failure_class_addressed (one of the skill's nineteen classes) so the change log
    reads like the inventory template. Unchanged text creates no version. bump='major' for a
    redesign. status is draft | testing | verified | retired; retiring reports every column
    that still depends on this one. rename_to is the only way to rename: other prompts that
    still reference the old @name are reported, never rewritten. Downstream columns become
    stale automatically; call impact_of_change for the rerun scope.
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
    matter: str,
    table: str,
    column: str,
    include_history: bool = False,
) -> dict[str, Any]:
    """Read one column in full: current prompt text, type, options, purpose, upstream and
    downstream dependencies (with kind and table), parameters it consumes or sources,
    staleness with reasons, and evaluation summary. include_history=true adds every prior
    prompt version with change notes and the change log.
    """
    return {
        **service.column_read(get_conn(), matter, table, column, include_history),
        "findings": [],
    }


@mcp.tool()
@_tool
def columns_find(
    matter: str,
    table: str | None = None,
    native_type: str | None = None,
    status: str | None = None,
    failure_class: str | None = None,
    consumes_parameter: str | None = None,
    stale: bool | None = None,
    name_contains: str | None = None,
    role: str | None = None,
    concept: str | None = None,
) -> dict[str, Any]:
    """Find columns across the matter by filter; returns summaries, not prompt text.

    Filters combine: table, native_type, status (draft | testing | verified | retired),
    failure_class (columns with an open failure of that class), consumes_parameter (bound to
    that shared parameter, directly or via its table's instructions), stale (true = directly
    or transitively stale), name_contains, role, concept. Use column_read for the full text.
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
        ),
        "findings": [],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def prompt_check(
    prompt_text: str,
    native_type: str,
    configured_options: list[str] | None = None,
    matter: str | None = None,
    table: str | None = None,
    column_name: str | None = None,
    column_position: int | None = None,
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
    nt = NATIVE_TYPE_ALIASES.get(native_type.strip().lower(), native_type.strip())
    if nt not in NATIVE_TYPES:
        raise PromptGraphError(f"native_type must be one of {', '.join(NATIVE_TYPES)}.")
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
    ctx = lint.PromptContext(nt, configured_options, column_name, column_position, cols)
    fs = lint.check_prompt(prompt_text, ctx, subject_name=column_name or "draft")
    return {
        "char_count": len(prompt_text),
        "native_type": nt,
        "references_checked": cols is not None,
        "fallback_terms_used": lint.fallback_terms_used(prompt_text),
        "vocabulary": list(FALLBACK_VOCABULARY),
        "findings": fs,
    }


@mcp.tool()
@_tool
def suite_check(
    matter: str,
    checks: list[str] | None = None,
    table: str | None = None,
) -> dict[str, Any]:
    """Check the whole suite for structural and consistency problems. Returns findings only.

    Families (all by default; pass checks=[...] to narrow): 'graph' (dependency cycles,
    unresolved or forward @Column references, ordering against the skill's staged pattern,
    a narrative column acting as control plane for several dependents, dependencies on
    retired columns); 'parameters' (orphaned parameters, unresolved parameters with
    consumers, a consuming table that never binds the value into its Table Instructions,
    resolved values absent from the bound text, dangling bindings); 'consistency' (date and
    currency pattern drift against the standard, an entity printed differently from the
    matter standard's exact name, the same concept extracted under different names or with
    different types/options/fallbacks across tables, missing or incomplete Table
    Instructions); 'prompts' (the prompt_check rules over every stored prompt).
    """
    return checks_mod.suite_check(get_conn(), matter, checks, table)


# ---------------------------------------------------------------------------
# Graph and staleness
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def impact_of_change(
    matter: str,
    table: str | None = None,
    column: str | None = None,
    parameter: str | None = None,
    new_value: str | None = None,
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
def staleness_report(matter: str, table: str | None = None) -> dict[str, Any]:
    """Which columns need a rerun and why, across the matter or for one table.

    'direct': the column's own prompt, its table's instructions, or a bound parameter changed
    after its last run. 'transitive': an upstream column (any dependency kind, any table) is
    stale or changed after this column's last run. 'never_run': no run recorded. Includes a
    dependency-ordered rerun sequence for the stale set.
    """
    conn = get_conn()
    m = service.get_matter(conn, matter)
    tid = int(service.get_table(conn, int(m["id"]), table)["id"]) if table else None
    return {"matter": m["name"], "table": table, **graph.staleness_report(conn, int(m["id"]), tid)}


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def parameter_set(
    matter: str,
    name: str,
    value: str | None = None,
    source_table: str | None = None,
    source_column: str | None = None,
    consumers: list[ConsumerBinding] | None = None,
    replace_consumers: bool = False,
    status: str | None = None,
    note: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Declare, resolve, or rebind a shared parameter: the cross-table dependency mechanism.

    Example: name='Target Legal Name', value='Harbor Logistics Holdings, LLC',
    source_table='Entity Register', source_column='Principal Entity', consumers=[{table:
    'Charter Documents', site: 'table_instructions'}, ...]. Consumers are added to existing
    bindings unless replace_consumers=true. A changed value marks every consumer stale and
    is what impact_of_change reads. status: unresolved | resolved | contested (defaults to
    resolved when a value is given). Reports bindings whose text does not contain the value.
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
    matter: str,
    table: str,
    started_at: str | None = None,
    note: str | None = None,
    evaluator: str | None = None,
    corpus_note: str | None = None,
    columns: list[str] | None = None,
    coverage_dimensions: list[str] | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Record that a table was run in Harvey, snapshotting the prompt version of each column.

    Staleness is computed against this snapshot, so record a run before logging results.
    columns limits the snapshot to a selective rerun. coverage_dimensions ticks the test-set
    checklist from the skill's evaluation log (keys: document_types, single_multi_subject,
    execution_states, amendments_compilations, express, silent, incorporated, defective,
    multiple_records, upstream_fallbacks, multi_hop, conditional, locked_cells, grouped);
    an unticked dimension is treated as open risk by coverage_check. started_at is ISO 8601
    and defaults to now.
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
    )


@mcp.tool()
@_tool
def eval_record(
    matter: str,
    table: str,
    results: list[EvalRecord],
    run_id: int | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Log evaluation results for a run, one record per (column, test document), in batch.

    Fields mirror the skill's evaluation-log-template.csv. Record passes as well as failures.
    failure_class must be one of the skill's nineteen classes (scope_leakage,
    concept_conflation, document_type_error, temporal_status_error, evidence_overstatement,
    holder_direction_error, silence_uncertainty_error, suppressed_value, type_rejection,
    vocabulary_drift, applicability_error, dependency_routing_error, dead_reference, cascade_error, stale_dependent_error, grouped_source_error,
    aggregation_error, output_leakage, verbosity); error_type is substantive | evidentiary |
    formatting. run_id defaults to the table's latest run. A failure stays open until a later
    result for the same column and document passes.
    """
    return evaluation.eval_record(get_conn(), matter, table, results, run_id, actor)


@mcp.tool()
@_tool
def failures_summary(
    matter: str, table: str | None = None, group_by: str = "class"
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
    matter: str,
    table: str,
    run_a: int | None = None,
    run_b: int | None = None,
    column: str | None = None,
) -> dict[str, Any]:
    """Compare two runs of a table over the same test documents: fixed, still failing, newly
    failing (regressions), plus documents present in only one run. Defaults to the two latest
    runs; run_a is the earlier, run_b the later. Narrow to one column with column=.
    """
    return evaluation.run_compare(get_conn(), matter, table, run_a, run_b, column)


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


@mcp.tool()
@_tool
def memo_outline_set(
    matter: str,
    sections: list[SectionRecord],
    name: str = "Diligence memo",
    actor: str | None = None,
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
def coverage_check(matter: str) -> dict[str, Any]:
    """The sufficiency test: can the table suite support the memo? Returns a gap report.

    Per assertion: reliably_covered (at least one source column has a run, no open failure,
    is not stale, and its table ticks every applicable test dimension); nominally_covered
    (sourced, but every source has an open failure, an unticked dimension, no run, or is
    stale); extraction_gap (an extraction assertion with no active source column: a schema
    defect); judgment_boundary (an attorney determination: correct behaviour, not a defect).
    Also lists unsourced columns (columns feeding no assertion) and tables with unticked
    dimensions.
    """
    return coverage.coverage_check(get_conn(), matter)


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
