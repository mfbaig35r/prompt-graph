"""table_readiness (Addendum A.4): is this table ready to run against the real vault?

Pure composition over checks that already exist. Findings are grouped by cause with a
plain count. No pass/fail verdict: readiness against a live client matter is a judgment,
and the tool's job is to make sure nothing is missed.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .checks import suite_check
from .evaluation import latest_run, open_failures, table_coverage
from .findings import Finding
from .freshness import freshness_findings, freshness_map
from .graph import staleness_map
from .service import get_matter, get_table, table_columns


def table_readiness(conn: sqlite3.Connection, matter: str, table: str) -> dict[str, Any]:
    m = get_matter(conn, matter)
    mid = int(m["id"])
    t = get_table(conn, mid, table)
    tid = int(t["id"])
    cols = table_columns(conn, tid)
    groups: dict[str, list[Finding]] = {
        "prompts": [],
        "graph": [],
        "parameters": [],
        "consistency": [],
        "status": [],
        "evaluation": [],
        "coverage_dimensions": [],
        "document_set": [],
    }

    # Deterministic checks scoped to this table.
    sc = suite_check(conn, m["name"], None, t["name"])
    # suite_check returns findings in family order with counts; re-split by walking families.
    idx = 0
    for fam in sc["checks_run"]:
        n = sc["counts"][fam]
        groups[fam].extend(sc["findings"][idx : idx + n])
        idx += n

    # Lifecycle: columns not yet verified, and columns never run or stale.
    smap = staleness_map(conn, mid)
    for c in cols:
        if c["status"] in ("draft", "testing"):
            groups["status"].append(
                Finding(
                    "COLUMN_NOT_VERIFIED",
                    "column",
                    int(c["id"]),
                    c["name"],
                    f"'{c['name']}' is in status {c['status']}.",
                    {"table": t["name"], "status": c["status"]},
                )
            )
        st = smap.get(int(c["id"]))
        if st and st["state"] in ("direct", "transitive"):
            groups["status"].append(
                Finding(
                    "COLUMN_STALE",
                    "column",
                    int(c["id"]),
                    c["name"],
                    f"'{c['name']}' is {st['state']}ly stale: " + "; ".join(st["reasons"]) + ".",
                    {"table": t["name"], "state": st["state"]},
                )
            )
        elif st and st["state"] == "never_run":
            groups["status"].append(
                Finding(
                    "COLUMN_NEVER_RUN",
                    "column",
                    int(c["id"]),
                    c["name"],
                    f"'{c['name']}' has no recorded run.",
                    {"table": t["name"]},
                )
            )

    # Unresolved parameters this table consumes.
    for p in conn.execute(
        """SELECT DISTINCT sp.name, sp.status FROM parameter_binding pb JOIN shared_parameter sp ON sp.id=pb.parameter_id
           WHERE pb.consuming_table_id=? AND sp.status!='resolved'""",
        (tid,),
    ):
        groups["parameters"].append(
            Finding(
                "PARAM_UNRESOLVED_CONSUMED",
                "table",
                tid,
                t["name"],
                f"'{t['name']}' consumes the shared parameter '{p['name']}', which is {p['status']}.",
                {"parameter": p["name"], "status": p["status"]},
            )
        )

    # Open failures from the latest results.
    run = latest_run(conn, tid)
    for c in cols:
        for r in open_failures(conn, int(c["id"])):
            groups["evaluation"].append(
                Finding(
                    "OPEN_FAILURE",
                    "column",
                    int(c["id"]),
                    c["name"],
                    f"'{c['name']}' has an open {r['failure_class'] or 'unclassified'} failure on '{r['test_document']}'.",
                    {
                        "table": t["name"],
                        "test_document": r["test_document"],
                        "failure_class": r["failure_class"],
                        "run_id": int(r["run_id"]),
                    },
                )
            )

    # Test-set coverage dimensions.
    cov = table_coverage(conn, tid)
    if run is not None and cov["unticked"]:
        groups["coverage_dimensions"].append(
            Finding(
                "COV_DIMENSION_UNTICKED",
                "table",
                tid,
                t["name"],
                f"The latest run of '{t['name']}' leaves {len(cov['unticked'])} of {cov['applicable_count']} test-set dimensions unticked.",
                {"unticked": cov["unticked"], "run_id": cov["run_id"]},
            )
        )

    # Document-set freshness.
    fmap = freshness_map(conn, mid)
    groups["document_set"].extend(freshness_findings(conn, mid, {tid: fmap[tid]}))

    counts = {k: len(v) for k, v in groups.items()}
    return {
        "matter": m["name"],
        "table": t["name"],
        "columns": len(cols),
        "last_run": {"run_id": int(run["id"]), "started_at": run["started_at"]} if run else None,
        "document_set": fmap[tid]["state"],
        "counts": counts,
        "total": sum(counts.values()),
        "by_cause": {k: [f.to_dict() for f in v] for k, v in groups.items()},
        "findings": [f for v in groups.values() for f in v],
    }
