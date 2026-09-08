"""Runs, evaluation results, failure summaries, and run comparison (requirements §7 P2).

`eval_result` mirrors the skill's evaluation-log-template.csv column for column. An "open
failure" is a (column, test document) pair whose most recent recorded result failed.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .constants import (
    COVERAGE_DIMENSION_KEYS,
    ERROR_TYPES,
    FAILURE_CLASS_ALIASES,
    FAILURE_CLASSES,
)
from .db import now
from .findings import Finding, PromptGraphError
from .models import EvalRecord, fold
from .service import (
    _provenance,
    current_instructions,
    current_prompt,
    get_column,
    get_matter,
    get_table,
    table_columns,
)


def normalise_failure_class(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    key = raw.strip().lower()
    if key in FAILURE_CLASS_ALIASES:
        return FAILURE_CLASS_ALIASES[key]
    slug = key.replace("/", "_").replace("-", "_").replace(" ", "_")
    return slug


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def run_record(
    conn: sqlite3.Connection,
    matter: str,
    table: str,
    started_at: str | None = None,
    note: str | None = None,
    evaluator: str | None = None,
    corpus_note: str | None = None,
    columns: list[str] | None = None,
    coverage_dimensions: list[str] | None = None,
    actor: str | None = None,
    documents_ready: int | None = None,
    documents_as_of: str | None = None,
) -> dict[str, Any]:
    from .freshness import latest_snapshot, record_snapshot, table_vault_project

    m = get_matter(conn, matter)
    t = get_table(conn, int(m["id"]), table)
    table_id = int(t["id"])
    findings: list[Finding] = []
    cols = table_columns(conn, table_id)
    project = table_vault_project(conn, t)
    if documents_ready is not None and not project:
        findings.append(
            Finding(
                "DOCSET_NO_PROJECT",
                "table",
                table_id,
                t["name"],
                f"A document count was given but '{t['name']}' has no vault project id, so no snapshot was recorded.",
                {},
            )
        )
    if columns:
        wanted = {c.strip().lower() for c in columns}
        chosen = [c for c in cols if c["name"].lower() in wanted]
        missing = wanted - {c["name"].lower() for c in chosen}
        if missing:
            raise PromptGraphError(f"Unknown columns for this table: {', '.join(sorted(missing))}.")
    else:
        chosen = cols
    dims: list[str] = []
    for d in coverage_dimensions or []:
        k = d.strip().lower().replace("-", "_").replace(" ", "_")
        if k not in COVERAGE_DIMENSION_KEYS:
            findings.append(
                Finding(
                    "COVERAGE_DIMENSION_UNKNOWN",
                    "run",
                    None,
                    t["name"],
                    f"'{d}' is not one of the fourteen test-set coverage dimensions.",
                    {"accepted": list(COVERAGE_DIMENSION_KEYS)},
                )
            )
        else:
            dims.append(k)
    if "grouped" in dims and not t["grouping_enabled"]:
        findings.append(
            Finding(
                "COVERAGE_DIMENSION_NOT_APPLICABLE",
                "run",
                None,
                t["name"],
                "The grouped-evidence dimension was ticked for a table that does not use grouping.",
                {},
            )
        )
    ti = current_instructions(conn, table_id)
    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            "INSERT INTO run (table_id, started_at, note, evaluator, corpus_note, created_at) VALUES (?,?,?,?,?,?)",
            (table_id, started_at or now(), note, evaluator, corpus_note, now()),
        )
        run_id = int(cur.lastrowid)
        persisted_started_at = conn.execute(
            "SELECT started_at FROM run WHERE id=?", (run_id,)
        ).fetchone()[0]
        docset = None
        if project:
            if documents_ready is not None:
                docset = record_snapshot(
                    conn,
                    int(m["id"]),
                    project,
                    "manual",
                    documents_ready,
                    None,
                    None,
                    "Recorded with run",
                    documents_as_of or persisted_started_at,
                    actor,
                )
            else:
                docset = latest_snapshot(conn, int(m["id"]), project)
            if docset is not None:
                conn.execute(
                    "UPDATE run SET document_set_snapshot_id=? WHERE id=?",
                    (int(docset["id"]), run_id),
                )
        snapshot: list[dict[str, Any]] = []
        for c in chosen:
            pv = current_prompt(conn, int(c["id"]))
            if pv is None:
                continue
            conn.execute(
                "INSERT INTO run_snapshot (run_id, column_id, prompt_version_id, instructions_version_id) VALUES (?,?,?,?)",
                (run_id, int(c["id"]), int(pv["id"]), int(ti["id"]) if ti else None),
            )
            snapshot.append({"column": c["name"], "version": pv["version"]})
        for k in dims:
            conn.execute(
                "INSERT OR IGNORE INTO run_coverage (run_id, dimension_key) VALUES (?,?)",
                (run_id, k),
            )
        _provenance(
            conn,
            "run",
            run_id,
            "record",
            "chat",
            actor,
            {"table": t["name"], "columns": len(snapshot)},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    if project and docset is None:
        findings.append(
            Finding(
                "DOCSET_UNRECORDED",
                "run",
                run_id,
                t["name"],
                f"No document-set snapshot exists for vault project {project}, so this run cannot be compared for freshness; give documents_ready or run freshness_check with refresh.",
                {"vault_project_id": project},
            )
        )
    return {
        "matter": m["name"],
        "table": t["name"],
        "run_id": run_id,
        "started_at": persisted_started_at,
        "instructions_version": int(ti["version"]) if ti else None,
        "document_set": {
            "snapshot_id": int(docset["id"]),
            "ready_count": docset["ready_count"],
            "observed_at": docset["observed_at"],
            "source": docset["source"],
        }
        if docset is not None
        else None,
        "snapshot": snapshot,
        "coverage_dimensions": dims,
        "findings": findings,
    }


def latest_run(conn: sqlite3.Connection, table_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM run WHERE table_id=? ORDER BY started_at DESC, id DESC LIMIT 1", (table_id,)
    ).fetchone()


def _get_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    r = conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
    if r is None:
        raise PromptGraphError(f"No run with id {run_id}.")
    return r


# ---------------------------------------------------------------------------
# Evaluation results
# ---------------------------------------------------------------------------


def eval_record(
    conn: sqlite3.Connection,
    matter: str,
    table: str,
    results: list[EvalRecord],
    run_id: int | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    m = get_matter(conn, matter)
    t = get_table(conn, int(m["id"]), table)
    table_id = int(t["id"])
    run = _get_run(conn, run_id) if run_id is not None else latest_run(conn, table_id)
    if run is None:
        raise PromptGraphError(
            f"No run recorded for table '{t['name']}'. Record the run first with run_record."
        )
    if int(run["table_id"]) != table_id:
        raise PromptGraphError(f"Run {run['id']} belongs to a different table.")
    findings: list[Finding] = []
    stored = 0
    passes = 0
    fails = 0
    conn.execute("BEGIN")
    try:
        for rec in results:
            col = get_column(conn, table_id, rec.column)
            col_id = int(col["id"])
            snap = conn.execute(
                """SELECT pv.version FROM run_snapshot rs JOIN prompt_version pv ON pv.id=rs.prompt_version_id
                   WHERE rs.run_id=? AND rs.column_id=?""",
                (int(run["id"]), col_id),
            ).fetchone()
            snap_version = snap["version"] if snap else None
            version = rec.prompt_version or snap_version
            if snap_version is None:
                findings.append(
                    Finding(
                        "RUN_COLUMN_NOT_IN_SNAPSHOT",
                        "eval",
                        None,
                        rec.column,
                        f"Column '{rec.column}' was not part of run {run['id']}'s snapshot.",
                        {"run_id": int(run["id"]), "test_document": rec.test_document},
                    )
                )
            elif rec.prompt_version and rec.prompt_version.strip().lower() != snap_version.lower():
                findings.append(
                    Finding(
                        "PROMPT_VERSION_MISMATCH",
                        "eval",
                        None,
                        rec.column,
                        f"The result cites prompt {rec.prompt_version} but run {run['id']} executed {snap_version}.",
                        {"run_id": int(run["id"]), "test_document": rec.test_document},
                    )
                )
            fc = normalise_failure_class(rec.failure_class)
            if fc is not None and fc not in FAILURE_CLASSES:
                findings.append(
                    Finding(
                        "FAILURE_CLASS_INVALID",
                        "eval",
                        None,
                        rec.column,
                        f"'{rec.failure_class}' is not one of the skill's nineteen failure classes.",
                        {"accepted": list(FAILURE_CLASSES), "test_document": rec.test_document},
                    )
                )
            et = rec.error_type.strip().lower() if rec.error_type else None
            if et is not None and et not in ERROR_TYPES:
                findings.append(
                    Finding(
                        "ERROR_TYPE_INVALID",
                        "eval",
                        None,
                        rec.column,
                        f"'{rec.error_type}' is not one of substantive, evidentiary, formatting.",
                        {"test_document": rec.test_document},
                    )
                )
            if rec.passed and (fc or et):
                findings.append(
                    Finding(
                        "FAILURE_FIELDS_ON_PASS",
                        "eval",
                        None,
                        rec.column,
                        "A passing result carries a failure class or error type; the log template leaves those blank for a pass.",
                        {"test_document": rec.test_document},
                    )
                )
            if not rec.passed and fc is None:
                findings.append(
                    Finding(
                        "FAILURE_CLASS_MISSING",
                        "eval",
                        None,
                        rec.column,
                        "A failing result has no failure class recorded.",
                        {"test_document": rec.test_document},
                    )
                )
            conn.execute(
                """INSERT INTO eval_result (run_id, column_id, test_document, prompt_version, actual_answer,
                       evidence_relied_on, expected_behavior, passed, failure_class, error_type, revision_note,
                       rerun_scope, result_after_rerun, regressions, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(run["id"]),
                    col_id,
                    rec.test_document.strip(),
                    version,
                    rec.actual_answer,
                    rec.evidence_relied_on,
                    rec.expected_behavior,
                    int(rec.passed),
                    fc,
                    et,
                    rec.revision_note,
                    rec.rerun_scope,
                    rec.result_after_rerun,
                    rec.regressions,
                    now(),
                ),
            )
            stored += 1
            passes += int(rec.passed)
            fails += int(not rec.passed)
        _provenance(conn, "run", int(run["id"]), "eval", "chat", actor, {"stored": stored})
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {
        "matter": m["name"],
        "table": t["name"],
        "run_id": int(run["id"]),
        "stored": stored,
        "passed": passes,
        "failed": fails,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Open failures
# ---------------------------------------------------------------------------

_LATEST_PER_DOC = """
    SELECT e.* FROM eval_result e
    JOIN run r ON r.id=e.run_id
    WHERE e.column_id=? AND NOT EXISTS (
        SELECT 1 FROM eval_result e2 JOIN run r2 ON r2.id=e2.run_id
        WHERE e2.column_id=e.column_id AND e2.test_document=e.test_document
          AND (r2.started_at > r.started_at OR (r2.started_at = r.started_at AND e2.id > e.id))
    )
"""


def latest_results(conn: sqlite3.Connection, column_id: int) -> list[sqlite3.Row]:
    return conn.execute(_LATEST_PER_DOC + " ORDER BY e.test_document", (column_id,)).fetchall()


def open_failures(conn: sqlite3.Connection, column_id: int) -> list[sqlite3.Row]:
    return [r for r in latest_results(conn, column_id) if not r["passed"]]


def column_eval_summary(conn: sqlite3.Connection, column_id: int) -> dict[str, Any]:
    runs = conn.execute(
        "SELECT r.id, r.started_at FROM run_snapshot rs JOIN run r ON r.id=rs.run_id WHERE rs.column_id=? ORDER BY r.started_at DESC, r.id DESC",
        (column_id,),
    ).fetchall()
    latest = latest_results(conn, column_id)
    fails = [r for r in latest if not r["passed"]]
    return {
        "runs": len(runs),
        "last_run": {"run_id": int(runs[0]["id"]), "started_at": runs[0]["started_at"]}
        if runs
        else None,
        "documents_tested": len(latest),
        "open_failures": len(fails),
        "open_failure_classes": sorted({r["failure_class"] for r in fails if r["failure_class"]}),
    }


def column_has_open_failure_class(
    conn: sqlite3.Connection, column_id: int, failure_class: str
) -> bool:
    fc = normalise_failure_class(failure_class)
    return any(r["failure_class"] == fc for r in open_failures(conn, column_id))


def failures_summary(
    conn: sqlite3.Connection,
    matter: str,
    table: str | None = None,
    group_by: str = "class",
) -> dict[str, Any]:
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    group_by = fold(group_by) or "class"
    if group_by not in ("class", "table", "column"):
        raise PromptGraphError("group_by must be class, table, or column.")
    tables = conn.execute(
        "SELECT * FROM review_table WHERE matter_id=? ORDER BY position, name", (matter_id,)
    ).fetchall()
    if table:
        t = get_table(conn, matter_id, table)
        tables = [t]
    items: list[dict[str, Any]] = []
    for t in tables:
        for c in table_columns(conn, int(t["id"])):
            for r in open_failures(conn, int(c["id"])):
                items.append(
                    {
                        "table": t["name"],
                        "column": c["name"],
                        "test_document": r["test_document"],
                        "prompt_version": r["prompt_version"],
                        "failure_class": r["failure_class"],
                        "error_type": r["error_type"],
                        "actual_answer": r["actual_answer"],
                        "expected_behavior": r["expected_behavior"],
                        "run_id": int(r["run_id"]),
                    }
                )
    key = {"class": "failure_class", "table": "table", "column": "column"}[group_by]
    groups: dict[str, dict[str, Any]] = {}
    for it in items:
        k = it[key] or "(unclassified)"
        g = groups.setdefault(
            k, {"count": 0, "tables": set(), "columns": set(), "classes": set(), "items": []}
        )
        g["count"] += 1
        g["tables"].add(it["table"])
        g["columns"].add(f"{it['table']} / {it['column']}")
        if it["failure_class"]:
            g["classes"].add(it["failure_class"])
        g["items"].append(it)
    out_groups = []
    for k, g in sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
        entry: dict[str, Any] = {
            "key": k,
            "label": FAILURE_CLASSES.get(k, k) if group_by == "class" else k,
            "count": g["count"],
            "tables": sorted(g["tables"]),
            "columns": sorted(g["columns"]),
            "classes": sorted(g["classes"]),
            "items": g["items"],
        }
        out_groups.append(entry)
    # Systematic signal: a class that appears in more than one table or more than two columns.
    findings: list[Finding] = []
    by_class: dict[str, set[str]] = {}
    for it in items:
        if it["failure_class"]:
            by_class.setdefault(it["failure_class"], set()).add(f"{it['table']} / {it['column']}")
    for fc, cols in by_class.items():
        if len(cols) >= 3 or len({c.split(" / ")[0] for c in cols}) >= 2:
            findings.append(
                Finding(
                    "FAILURE_CLASS_RECURRING",
                    "matter",
                    matter_id,
                    m["name"],
                    f"The failure class '{FAILURE_CLASSES.get(fc, fc)}' is open on {len(cols)} columns across {len({c.split(' / ')[0] for c in cols})} tables.",
                    {"failure_class": fc, "columns": sorted(cols)},
                )
            )
    return {
        "matter": m["name"],
        "open_failures": len(items),
        "group_by": group_by,
        "groups": out_groups,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Run comparison
# ---------------------------------------------------------------------------


def run_compare(
    conn: sqlite3.Connection,
    matter: str,
    table: str,
    run_a: int | None = None,
    run_b: int | None = None,
    column: str | None = None,
) -> dict[str, Any]:
    m = get_matter(conn, matter)
    t = get_table(conn, int(m["id"]), table)
    table_id = int(t["id"])
    runs = conn.execute(
        "SELECT * FROM run WHERE table_id=? ORDER BY started_at DESC, id DESC LIMIT 2", (table_id,)
    ).fetchall()
    if run_b is None and run_a is None:
        if len(runs) < 2:
            raise PromptGraphError(
                "This table has fewer than two runs recorded; nothing to compare."
            )
        rb, ra = runs[0], runs[1]
    else:
        if run_a is None or run_b is None:
            raise PromptGraphError("Give both run ids, or neither to compare the two latest runs.")
        ra, rb = _get_run(conn, run_a), _get_run(conn, run_b)
    for r in (ra, rb):
        if int(r["table_id"]) != table_id:
            raise PromptGraphError(f"Run {r['id']} belongs to a different table.")
    cols = table_columns(conn, table_id, include_retired=True)
    if column:
        cols = [get_column(conn, table_id, column)]

    def results_for(run_id: int, col_id: int) -> dict[str, sqlite3.Row]:
        rows = conn.execute(
            "SELECT * FROM eval_result WHERE run_id=? AND column_id=? ORDER BY id", (run_id, col_id)
        ).fetchall()
        return {r["test_document"]: r for r in rows}  # last result per document wins

    per_column: list[dict[str, Any]] = []
    totals = {
        "fixed": 0,
        "still_failing": 0,
        "newly_failing": 0,
        "still_passing": 0,
        "only_in_earlier": 0,
        "only_in_later": 0,
    }
    for c in cols:
        a = results_for(int(ra["id"]), int(c["id"]))
        b = results_for(int(rb["id"]), int(c["id"]))
        if not a and not b:
            continue
        va = conn.execute(
            "SELECT pv.version FROM run_snapshot rs JOIN prompt_version pv ON pv.id=rs.prompt_version_id WHERE rs.run_id=? AND rs.column_id=?",
            (int(ra["id"]), int(c["id"])),
        ).fetchone()
        vb = conn.execute(
            "SELECT pv.version FROM run_snapshot rs JOIN prompt_version pv ON pv.id=rs.prompt_version_id WHERE rs.run_id=? AND rs.column_id=?",
            (int(rb["id"]), int(c["id"])),
        ).fetchone()
        buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in totals}
        for doc in sorted(set(a) | set(b)):
            ra_, rb_ = a.get(doc), b.get(doc)
            if ra_ is None:
                buckets["only_in_later"].append(
                    {"document": doc, "later": "pass" if rb_["passed"] else "fail"}
                )
            elif rb_ is None:
                buckets["only_in_earlier"].append(
                    {"document": doc, "earlier": "pass" if ra_["passed"] else "fail"}
                )
            else:
                entry = {
                    "document": doc,
                    "earlier_answer": ra_["actual_answer"],
                    "later_answer": rb_["actual_answer"],
                    "earlier_class": ra_["failure_class"],
                    "later_class": rb_["failure_class"],
                }
                if not ra_["passed"] and rb_["passed"]:
                    buckets["fixed"].append(entry)
                elif not ra_["passed"] and not rb_["passed"]:
                    buckets["still_failing"].append(entry)
                elif ra_["passed"] and not rb_["passed"]:
                    buckets["newly_failing"].append(entry)
                else:
                    buckets["still_passing"].append(entry)
        for k in totals:
            totals[k] += len(buckets[k])
        per_column.append(
            {
                "column": c["name"],
                "earlier_version": va["version"] if va else None,
                "later_version": vb["version"] if vb else None,
                **{k: buckets[k] for k in ("fixed", "still_failing", "newly_failing")},
                "still_passing_count": len(buckets["still_passing"]),
                "only_in_earlier": buckets["only_in_earlier"],
                "only_in_later": buckets["only_in_later"],
            }
        )
    findings: list[Finding] = []
    for pc in per_column:
        if pc["newly_failing"]:
            findings.append(
                Finding(
                    "REGRESSION",
                    "column",
                    None,
                    pc["column"],
                    f"{len(pc['newly_failing'])} document(s) passed in run {ra['id']} and fail in run {rb['id']}.",
                    {
                        "documents": [d["document"] for d in pc["newly_failing"]],
                        "earlier_version": pc["earlier_version"],
                        "later_version": pc["later_version"],
                    },
                )
            )
    return {
        "matter": m["name"],
        "table": t["name"],
        "earlier_run": {
            "run_id": int(ra["id"]),
            "started_at": ra["started_at"],
            "note": ra["note"],
        },
        "later_run": {"run_id": int(rb["id"]), "started_at": rb["started_at"], "note": rb["note"]},
        "totals": totals,
        "columns": per_column,
        "findings": findings,
    }


def table_coverage(conn: sqlite3.Connection, table_id: int) -> dict[str, Any]:
    """Dimensions ticked in the table's latest run, and those still open."""
    t = conn.execute("SELECT * FROM review_table WHERE id=?", (table_id,)).fetchone()
    run = latest_run(conn, table_id)
    ticked: set[str] = set()
    if run is not None:
        ticked = {
            r["dimension_key"]
            for r in conn.execute(
                "SELECT dimension_key FROM run_coverage WHERE run_id=?", (int(run["id"]),)
            )
        }
    dims = conn.execute("SELECT * FROM coverage_dimension ORDER BY position").fetchall()
    applicable = [d for d in dims if not d["requires_grouping"] or t["grouping_enabled"]]
    unticked = [d["key"] for d in applicable if d["key"] not in ticked]
    return {
        "has_run": run is not None,
        "run_id": int(run["id"]) if run else None,
        "ticked": sorted(ticked),
        "unticked": unticked,
        "applicable_count": len(applicable),
    }
