"""Suite-level state for matter_open (absorbs the requirements' matter_overview)."""

from __future__ import annotations

import sqlite3
from typing import Any

from .evaluation import latest_run, open_failures, table_coverage
from .graph import staleness_map
from .parameters import parameters_list
from .service import current_instructions, effective_standard, table_columns


def matter_overview(conn: sqlite3.Connection, m: sqlite3.Row) -> dict[str, Any]:
    matter_id = int(m["id"])
    smap = staleness_map(conn, matter_id)
    tables_out: list[dict[str, Any]] = []
    total_cols = 0
    total_open = 0
    stale_total = {"never_run": 0, "current": 0, "direct": 0, "transitive": 0}
    for t in conn.execute(
        "SELECT * FROM review_table WHERE matter_id=? ORDER BY position, name", (matter_id,)
    ):
        cols = table_columns(conn, int(t["id"]), include_retired=True)
        active = [c for c in cols if c["status"] != "retired"]
        status_counts: dict[str, int] = {}
        for c in cols:
            status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
        st_counts = {"never_run": 0, "current": 0, "direct": 0, "transitive": 0}
        open_f = 0
        for c in active:
            s = smap.get(int(c["id"]))
            if s:
                st_counts[s["state"]] += 1
                stale_total[s["state"]] += 1
            open_f += len(open_failures(conn, int(c["id"])))
        ti = current_instructions(conn, int(t["id"]))
        run = latest_run(conn, int(t["id"]))
        cov = table_coverage(conn, int(t["id"]))
        total_cols += len(active)
        total_open += open_f
        tables_out.append(
            {
                "table": t["name"],
                "review_unit": t["review_unit"],
                "stage": t["stage"],
                "grouping_enabled": bool(t["grouping_enabled"]),
                "columns": len(active),
                "status_counts": status_counts,
                "instructions_version": int(ti["version"]) if ti else None,
                "last_run": {"run_id": int(run["id"]), "started_at": run["started_at"]}
                if run
                else None,
                "staleness": st_counts,
                "open_failures": open_f,
                "coverage_unticked": len(cov["unticked"]) if cov["has_run"] else None,
            }
        )
    params = parameters_list(conn, matter_id)
    outline = conn.execute(
        "SELECT name, version FROM memo_outline WHERE matter_id=? AND is_current=1", (matter_id,)
    ).fetchone()
    std = effective_standard(conn, matter_id)
    return {
        "matter": m["name"],
        "matter_id": matter_id,
        "objective": m["objective"],
        "side": m["side"],
        "status": m["status"],
        "tables": tables_out,
        "table_count": len(tables_out),
        "column_count": total_cols,
        "staleness": stale_total,
        "open_failures": total_open,
        "parameters": params,
        "unresolved_parameters": [p["name"] for p in params if p["status"] != "resolved"],
        "memo_outline": {"name": outline["name"], "version": int(outline["version"])}
        if outline
        else None,
        "standard": {
            "firm_version": std["firm_version"],
            "matter_version": std["matter_version"],
            "date_pattern": std["date_pattern"],
            "currency_pattern": std["currency_pattern"],
            "entities": [e["name"] for e in std["entities"]],
            "overridden_by_firm": std["overridden_by_firm"],
        },
    }
