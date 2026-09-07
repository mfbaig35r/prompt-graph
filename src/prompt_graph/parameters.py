"""Shared parameters: the cross-table dependency mechanism (requirements §6, §7)."""

from __future__ import annotations

import sqlite3
from typing import Any

from .constants import BINDING_SITES, PARAMETER_STATUSES
from .db import now
from .findings import Finding, PromptGraphError
from .models import ConsumerBinding
from .service import (
    _norm,
    _provenance,
    current_instructions,
    current_prompt,
    get_column,
    get_matter,
    get_parameter,
    get_table,
    table_columns,
)


def rebuild_parameter_edges(conn: sqlite3.Connection, parameter_id: int) -> int:
    """Materialise cross_table_parameter edges from the source column to every consumer column."""
    p = conn.execute("SELECT * FROM shared_parameter WHERE id=?", (parameter_id,)).fetchone()
    conn.execute(
        "DELETE FROM dependency WHERE kind='cross_table_parameter' AND parameter_id=?",
        (parameter_id,),
    )
    if p is None or p["source_column_id"] is None:
        return 0
    src = int(p["source_column_id"])
    n = 0
    for b in conn.execute("SELECT * FROM parameter_binding WHERE parameter_id=?", (parameter_id,)):
        targets: list[int]
        if b["consuming_column_id"] is not None:
            targets = [int(b["consuming_column_id"])]
        else:
            targets = [int(c["id"]) for c in table_columns(conn, int(b["consuming_table_id"]))]
        for t in targets:
            if t == src:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO dependency (from_column_id, to_column_id, kind, declared_by, parameter_id)
                   VALUES (?, ?, 'cross_table_parameter', 'parameter', ?)""",
                (src, t, parameter_id),
            )
            n += 1
    return n


def rebuild_all_parameter_edges(conn: sqlite3.Connection, matter_id: int) -> None:
    for p in conn.execute("SELECT id FROM shared_parameter WHERE matter_id=?", (matter_id,)):
        rebuild_parameter_edges(conn, int(p["id"]))


def parameter_set(
    conn: sqlite3.Connection,
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
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    name = _norm(name)
    if status is not None and status not in PARAMETER_STATUSES:
        raise PromptGraphError(f"status must be one of {', '.join(PARAMETER_STATUSES)}.")
    findings: list[Finding] = []

    src_table_id: int | None = None
    src_col_id: int | None = None
    if source_table:
        st = get_table(conn, matter_id, source_table)
        src_table_id = int(st["id"])
        if source_column:
            src_col_id = int(get_column(conn, src_table_id, source_column)["id"])
    elif source_column:
        raise PromptGraphError("source_column needs a source_table.")

    conn.execute("BEGIN")
    try:
        existing = conn.execute(
            "SELECT * FROM shared_parameter WHERE matter_id=? AND name=?", (matter_id, name)
        ).fetchone()
        previous_value = existing["value"] if existing else None
        value_changed = value is not None and value != previous_value
        if existing is None:
            new_status = status or ("resolved" if value is not None else "unresolved")
            cur = conn.execute(
                """INSERT INTO shared_parameter (matter_id, name, value, source_column_id, source_table_id,
                       resolved_at, status, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    matter_id,
                    name,
                    value,
                    src_col_id,
                    src_table_id,
                    now() if value is not None else None,
                    new_status,
                    note,
                    now(),
                ),
            )
            pid = int(cur.lastrowid)
            _provenance(
                conn, "parameter", pid, "create", "chat", actor, {"name": name, "value": value}
            )
        else:
            pid = int(existing["id"])
            new_status = status or (
                "resolved"
                if value_changed or (value is not None and existing["status"] == "unresolved")
                else existing["status"]
            )
            conn.execute(
                """UPDATE shared_parameter SET value=COALESCE(?, value),
                       source_column_id=COALESCE(?, source_column_id),
                       source_table_id=COALESCE(?, source_table_id),
                       resolved_at=CASE WHEN ? THEN ? ELSE resolved_at END,
                       status=?, note=COALESCE(?, note) WHERE id=?""",
                (value, src_col_id, src_table_id, int(value_changed), now(), new_status, note, pid),
            )
            if value_changed:
                _provenance(
                    conn,
                    "parameter",
                    pid,
                    "resolve",
                    "chat",
                    actor,
                    {"from": previous_value, "to": value},
                )
        if replace_consumers:
            conn.execute("DELETE FROM parameter_binding WHERE parameter_id=?", (pid,))
        for c in consumers or []:
            if c.site not in BINDING_SITES:
                raise PromptGraphError(f"binding site must be one of {', '.join(BINDING_SITES)}.")
            ct = get_table(conn, matter_id, c.table)
            cc_id = int(get_column(conn, int(ct["id"]), c.column)["id"]) if c.column else None
            if c.site == "column_prompt" and cc_id is None:
                raise PromptGraphError("A column_prompt binding needs a column name.")
            conn.execute(
                """INSERT OR IGNORE INTO parameter_binding (parameter_id, consuming_table_id, consuming_column_id, binding_site)
                   VALUES (?,?,?,?)""",
                (pid, int(ct["id"]), cc_id, c.site),
            )
        edges = rebuild_parameter_edges(conn, pid)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    p = get_parameter(conn, matter_id, name)
    findings.extend(check_parameter(conn, p))
    return {
        "matter": m["name"],
        "parameter": p["name"],
        "parameter_id": pid,
        "value": p["value"],
        "previous_value": previous_value,
        "value_changed": value_changed,
        "status": p["status"],
        "source": _source_dict(conn, p),
        "consumers": bindings_list(conn, pid),
        "dependency_edges": edges,
        "findings": findings,
    }


def _source_dict(conn: sqlite3.Connection, p: sqlite3.Row) -> dict[str, Any] | None:
    if p["source_table_id"] is None:
        return None
    t = conn.execute("SELECT name FROM review_table WHERE id=?", (p["source_table_id"],)).fetchone()
    c = (
        conn.execute(
            "SELECT name, status FROM column_def WHERE id=?", (p["source_column_id"],)
        ).fetchone()
        if p["source_column_id"]
        else None
    )
    return {
        "table": t["name"] if t else None,
        "column": c["name"] if c else None,
        "column_status": c["status"] if c else None,
    }


def bindings_list(conn: sqlite3.Connection, parameter_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT pb.binding_site, rt.name AS table_name, c.name AS column_name FROM parameter_binding pb
           JOIN review_table rt ON rt.id=pb.consuming_table_id
           LEFT JOIN column_def c ON c.id=pb.consuming_column_id
           WHERE pb.parameter_id=? ORDER BY rt.position, rt.name, c.position""",
        (parameter_id,),
    ).fetchall()
    return [
        {"table": r["table_name"], "column": r["column_name"], "site": r["binding_site"]}
        for r in rows
    ]


def check_parameter(conn: sqlite3.Connection, p: sqlite3.Row) -> list[Finding]:
    """Deterministic checks on one parameter (also used by suite_check)."""
    findings: list[Finding] = []
    pid = int(p["id"])
    bindings = conn.execute(
        "SELECT * FROM parameter_binding WHERE parameter_id=?", (pid,)
    ).fetchall()
    if not bindings:
        findings.append(
            Finding(
                "PARAM_ORPHANED",
                "parameter",
                pid,
                p["name"],
                "This shared parameter has no consuming table or column bound to it.",
                {"status": p["status"], "value": p["value"]},
            )
        )
    if p["status"] != "resolved" and bindings:
        findings.append(
            Finding(
                "PARAM_UNRESOLVED_CONSUMED",
                "parameter",
                pid,
                p["name"],
                f"This parameter is {p['status']} but {len(bindings)} binding(s) consume it.",
                {"status": p["status"], "bindings": bindings_list(conn, pid)},
            )
        )
    if p["source_column_id"] is not None:
        sc = conn.execute(
            "SELECT name, status FROM column_def WHERE id=?", (p["source_column_id"],)
        ).fetchone()
        if sc and sc["status"] == "retired":
            findings.append(
                Finding(
                    "PARAM_SOURCE_RETIRED",
                    "parameter",
                    pid,
                    p["name"],
                    f"The source column '{sc['name']}' is retired.",
                    {"source_column": sc["name"]},
                )
            )
    tables_bound: dict[int, set[str]] = {}
    for b in bindings:
        tables_bound.setdefault(int(b["consuming_table_id"]), set()).add(b["binding_site"])
        if b["consuming_column_id"] is not None:
            cc = conn.execute(
                "SELECT name, status FROM column_def WHERE id=?", (b["consuming_column_id"],)
            ).fetchone()
            if cc and cc["status"] == "retired":
                findings.append(
                    Finding(
                        "BINDING_DANGLING",
                        "binding",
                        int(b["id"]),
                        p["name"],
                        f"A binding points at the retired column '{cc['name']}'.",
                        {"column": cc["name"]},
                    )
                )
    for table_id, sites in tables_bound.items():
        t = conn.execute("SELECT name FROM review_table WHERE id=?", (table_id,)).fetchone()
        if "table_instructions" not in sites:
            findings.append(
                Finding(
                    "PARAM_NOT_BOUND_TO_INSTRUCTIONS",
                    "parameter",
                    pid,
                    p["name"],
                    f"Table '{t['name']}' consumes this parameter in column prompts only, not in its Table Instructions.",
                    {"table": t["name"], "sites": sorted(sites)},
                )
            )
    if p["value"]:
        val = p["value"].lower()
        for b in bindings:
            t = conn.execute(
                "SELECT name FROM review_table WHERE id=?", (b["consuming_table_id"],)
            ).fetchone()
            if b["binding_site"] == "table_instructions":
                ti = current_instructions(conn, int(b["consuming_table_id"]))
                if ti is None or val not in ti["text"].lower():
                    findings.append(
                        Finding(
                            "PARAM_VALUE_ABSENT_FROM_INSTRUCTIONS",
                            "table",
                            int(b["consuming_table_id"]),
                            t["name"],
                            f"The current Table Instructions of '{t['name']}' do not contain the resolved value of '{p['name']}'.",
                            {
                                "parameter": p["name"],
                                "value": p["value"],
                                "instructions_version": int(ti["version"]) if ti else None,
                            },
                        )
                    )
            elif b["consuming_column_id"] is not None:
                pv = current_prompt(conn, int(b["consuming_column_id"]))
                cc = conn.execute(
                    "SELECT name FROM column_def WHERE id=?", (b["consuming_column_id"],)
                ).fetchone()
                if pv is None or val not in pv["text"].lower():
                    findings.append(
                        Finding(
                            "PARAM_VALUE_ABSENT_FROM_PROMPT",
                            "column",
                            int(b["consuming_column_id"]),
                            cc["name"],
                            f"The current prompt of '{t['name']} / {cc['name']}' does not contain the resolved value of '{p['name']}'.",
                            {
                                "parameter": p["name"],
                                "value": p["value"],
                                "version": pv["version"] if pv else None,
                            },
                        )
                    )
    return findings


def parameters_list(conn: sqlite3.Connection, matter_id: int) -> list[dict[str, Any]]:
    out = []
    for p in conn.execute(
        "SELECT * FROM shared_parameter WHERE matter_id=? ORDER BY name", (matter_id,)
    ):
        out.append(
            {
                "name": p["name"],
                "value": p["value"],
                "status": p["status"],
                "source": _source_dict(conn, p),
                "consumer_count": conn.execute(
                    "SELECT COUNT(*) FROM parameter_binding WHERE parameter_id=?", (p["id"],)
                ).fetchone()[0],
                "resolved_at": p["resolved_at"],
            }
        )
    return out
