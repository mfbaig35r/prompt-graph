"""Memo coverage: the sufficiency test (requirements §9).

The memo outline is the target. Each assertion is either `extraction` (a column can supply
the evidence) or `judgment` (the attorney makes the determination). Those two are never
collapsed: an unsourced extraction assertion is an extraction gap; a judgment assertion is a
judgment boundary and is reported as correct behaviour, with whatever evidence inputs the
attorney will consult.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .constants import ASSERTION_KINDS
from .db import now
from .evaluation import column_eval_summary, table_coverage
from .findings import Finding, PromptGraphError
from .graph import staleness_map
from .models import SectionRecord
from .service import _provenance, get_column, get_matter, get_table, table_columns


def memo_outline_set(
    conn: sqlite3.Connection,
    matter: str,
    sections: list[SectionRecord],
    name: str = "Diligence memo",
    actor: str | None = None,
) -> dict[str, Any]:
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    findings: list[Finding] = []
    for s in sections:
        for a in s.assertions:
            if a.kind not in ASSERTION_KINDS:
                raise PromptGraphError(
                    f"Assertion '{a.text[:60]}' has kind '{a.kind}'; it must be 'extraction' or 'judgment'."
                )
    prev = conn.execute(
        "SELECT * FROM memo_outline WHERE matter_id=? AND is_current=1", (matter_id,)
    ).fetchone()
    version = int(prev["version"]) + 1 if prev else 1
    counts = {"sections": 0, "assertions": 0, "extraction": 0, "judgment": 0, "sources": 0}
    conn.execute("BEGIN")
    try:
        conn.execute("UPDATE memo_outline SET is_current=0 WHERE matter_id=?", (matter_id,))
        cur = conn.execute(
            "INSERT INTO memo_outline (matter_id, name, version, created_at, is_current) VALUES (?,?,?,?,1)",
            (matter_id, name, version, now()),
        )
        outline_id = int(cur.lastrowid)
        for spos, s in enumerate(sections, start=1):
            sc = conn.execute(
                "INSERT INTO memo_section (outline_id, name, position) VALUES (?,?,?)",
                (outline_id, s.name.strip(), spos),
            )
            counts["sections"] += 1
            for apos, a in enumerate(s.assertions, start=1):
                ac = conn.execute(
                    "INSERT INTO memo_assertion (section_id, text, position, kind, note) VALUES (?,?,?,?,?)",
                    (int(sc.lastrowid), a.text.strip(), apos, a.kind, a.note),
                )
                counts["assertions"] += 1
                counts[a.kind] += 1
                for src in a.sources or []:
                    try:
                        t = get_table(conn, matter_id, src.table)
                        c = get_column(conn, int(t["id"]), src.column)
                    except PromptGraphError as e:
                        findings.append(
                            Finding(
                                "COV_SOURCE_UNRESOLVED",
                                "assertion",
                                int(ac.lastrowid),
                                a.text[:80],
                                f"The source '{src.table}' / '{src.column}' does not match a stored column.",
                                {"section": s.name, "detail": str(e)},
                            )
                        )
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO assertion_source (assertion_id, column_id, note) VALUES (?,?,?)",
                        (int(ac.lastrowid), int(c["id"]), src.note),
                    )
                    counts["sources"] += 1
        _provenance(
            conn, "memo_outline", outline_id, "set", "chat", actor, {"version": version, **counts}
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {
        "matter": m["name"],
        "outline": name,
        "version": version,
        **counts,
        "findings": findings,
    }


def coverage_check(conn: sqlite3.Connection, matter: str) -> dict[str, Any]:
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    outline = conn.execute(
        "SELECT * FROM memo_outline WHERE matter_id=? AND is_current=1", (matter_id,)
    ).fetchone()
    if outline is None:
        raise PromptGraphError(
            "No memo outline is stored for this matter. Use memo_outline_set to capture the memo's sections and assertions first."
        )
    findings: list[Finding] = []
    smap = staleness_map(conn, matter_id)
    tcov_cache: dict[int, dict[str, Any]] = {}

    def column_reliability(col_id: int) -> dict[str, Any]:
        c = conn.execute(
            "SELECT c.*, rt.name AS table_name FROM column_def c JOIN review_table rt ON rt.id=c.table_id WHERE c.id=?",
            (col_id,),
        ).fetchone()
        reasons: list[str] = []
        if c["status"] == "retired":
            reasons.append("column is retired")
        ev = column_eval_summary(conn, col_id)
        if ev["runs"] == 0:
            reasons.append("no run recorded")
        if ev["open_failures"]:
            reasons.append(
                f"{ev['open_failures']} open failure(s): {', '.join(ev['open_failure_classes']) or 'unclassified'}"
            )
        st = smap.get(col_id)
        if st and st["state"] in ("direct", "transitive"):
            reasons.append(f"{st['state']}ly stale")
        tid = int(c["table_id"])
        if tid not in tcov_cache:
            tcov_cache[tid] = table_coverage(conn, tid)
        tc = tcov_cache[tid]
        if tc["has_run"] and tc["unticked"]:
            reasons.append(
                f"{len(tc['unticked'])} test-set dimension(s) unticked for table '{c['table_name']}'"
            )
        return {
            "table": c["table_name"],
            "column": c["name"],
            "status": c["status"],
            "reliable": not reasons,
            "reasons": reasons,
        }

    sections_out: list[dict[str, Any]] = []
    totals = {
        "assertions": 0,
        "reliably_covered": 0,
        "nominally_covered": 0,
        "extraction_gap": 0,
        "judgment_boundary": 0,
    }
    sourced_column_ids: set[int] = set()
    sections = conn.execute(
        "SELECT * FROM memo_section WHERE outline_id=? ORDER BY position", (int(outline["id"]),)
    ).fetchall()
    for s in sections:
        assertions_out: list[dict[str, Any]] = []
        for a in conn.execute(
            "SELECT * FROM memo_assertion WHERE section_id=? ORDER BY position", (int(s["id"]),)
        ):
            srcs = conn.execute(
                "SELECT column_id, note FROM assertion_source WHERE assertion_id=?", (int(a["id"]),)
            ).fetchall()
            src_info = [column_reliability(int(r["column_id"])) for r in srcs]
            for r in srcs:
                sourced_column_ids.add(int(r["column_id"]))
            totals["assertions"] += 1
            entry: dict[str, Any] = {
                "assertion": a["text"],
                "kind": a["kind"],
                "sources": src_info,
                "note": a["note"],
            }
            if a["kind"] == "judgment":
                entry["status"] = "judgment_boundary"
                totals["judgment_boundary"] += 1
                findings.append(
                    Finding(
                        "COV_JUDGMENT_BOUNDARY",
                        "assertion",
                        int(a["id"]),
                        a["text"][:80],
                        f"The assertion '{a['text'][:80]}' in section '{s['name']}' is a determination the attorney supplies; the tables provide {len(src_info)} evidence input(s).",
                        {
                            "section": s["name"],
                            "evidence_inputs": [f"{x['table']} / {x['column']}" for x in src_info],
                        },
                    )
                )
            elif not src_info:
                entry["status"] = "extraction_gap"
                totals["extraction_gap"] += 1
                findings.append(
                    Finding(
                        "COV_EXTRACTION_GAP",
                        "assertion",
                        int(a["id"]),
                        a["text"][:80],
                        f"No column supplies evidence for the assertion '{a['text'][:80]}' in section '{s['name']}'.",
                        {"section": s["name"]},
                    )
                )
            else:
                active = [x for x in src_info if x["status"] != "retired"]
                for x in src_info:
                    if x["status"] == "retired":
                        findings.append(
                            Finding(
                                "COV_SOURCE_RETIRED",
                                "assertion",
                                int(a["id"]),
                                a["text"][:80],
                                f"The assertion '{a['text'][:80]}' is sourced from '{x['table']} / {x['column']}', which is retired.",
                                {"section": s["name"]},
                            )
                        )
                if not active:
                    entry["status"] = "extraction_gap"
                    totals["extraction_gap"] += 1
                    findings.append(
                        Finding(
                            "COV_EXTRACTION_GAP",
                            "assertion",
                            int(a["id"]),
                            a["text"][:80],
                            f"Every column sourced for the assertion '{a['text'][:80]}' in section '{s['name']}' is retired.",
                            {"section": s["name"]},
                        )
                    )
                elif any(x["reliable"] for x in active):
                    entry["status"] = "reliably_covered"
                    totals["reliably_covered"] += 1
                else:
                    entry["status"] = "nominally_covered"
                    totals["nominally_covered"] += 1
                    findings.append(
                        Finding(
                            "COV_NOMINAL_ONLY",
                            "assertion",
                            int(a["id"]),
                            a["text"][:80],
                            f"Every column sourced for the assertion '{a['text'][:80]}' in section '{s['name']}' has an open failure, an unticked test dimension, no run, or is stale.",
                            {
                                "section": s["name"],
                                "sources": [
                                    {
                                        "column": f"{x['table']} / {x['column']}",
                                        "reasons": x["reasons"],
                                    }
                                    for x in active
                                ],
                            },
                        )
                    )
                    for x in active:
                        if any(r.endswith("stale") for r in x["reasons"]):
                            findings.append(
                                Finding(
                                    "COV_SOURCE_STALE",
                                    "column",
                                    None,
                                    x["column"],
                                    f"'{x['table']} / {x['column']}' feeds the assertion '{a['text'][:60]}' and is stale.",
                                    {"section": s["name"]},
                                )
                            )
            assertions_out.append(entry)
        sections_out.append({"section": s["name"], "assertions": assertions_out})

    # Columns feeding no assertion.
    unsourced: list[dict[str, Any]] = []
    for t in conn.execute(
        "SELECT * FROM review_table WHERE matter_id=? ORDER BY position, name", (matter_id,)
    ):
        for c in table_columns(conn, int(t["id"])):
            if int(c["id"]) not in sourced_column_ids:
                unsourced.append(
                    {
                        "table": t["name"],
                        "column": c["name"],
                        "native_type": c["native_type"],
                        "role": c["role"],
                        "status": c["status"],
                    }
                )
                findings.append(
                    Finding(
                        "COV_UNSOURCED_COLUMN",
                        "column",
                        int(c["id"]),
                        c["name"],
                        f"'{t['name']} / {c['name']}' feeds no assertion in the memo outline.",
                        {"table": t["name"], "native_type": c["native_type"], "role": c["role"]},
                    )
                )
    # Tables whose latest run leaves dimensions unticked.
    for tid, tc in tcov_cache.items():
        if tc["has_run"] and tc["unticked"]:
            t = conn.execute("SELECT name FROM review_table WHERE id=?", (tid,)).fetchone()
            findings.append(
                Finding(
                    "COV_DIMENSION_UNTICKED",
                    "table",
                    tid,
                    t["name"],
                    f"The latest run of '{t['name']}' leaves {len(tc['unticked'])} of {tc['applicable_count']} test-set dimensions unticked.",
                    {"unticked": tc["unticked"], "run_id": tc["run_id"]},
                )
            )
    return {
        "matter": m["name"],
        "outline": outline["name"],
        "outline_version": int(outline["version"]),
        "totals": totals,
        "sections": sections_out,
        "unsourced_columns": unsourced,
        "findings": findings,
    }
