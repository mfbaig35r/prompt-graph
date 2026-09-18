"""Matter export (Addendum A.3): one JSON document recording how the diligence was conducted.

Everything the database knows about a matter at a point in time: the standard in effect,
tables and Table Instructions with versions, every column with its full version history,
the dependency graph, shared parameters and bindings, runs with their prompt-version and
document-set snapshots, evaluation results, coverage state, and provenance. Versioned by
`export_format_version` so old exports stay readable after the schema moves.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .db import db_path, now
from .findings import PromptGraphError
from .service import effective_standard, get_matter

EXPORT_FORMAT_VERSION = 2


def _rows(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, args)]


def build_export(conn: sqlite3.Connection, matter: str) -> dict[str, Any]:
    from . import coverage

    m = get_matter(conn, matter)
    mid = int(m["id"])
    doc: dict[str, Any] = {
        "export_format_version": EXPORT_FORMAT_VERSION,
        "exported_at": now(),
        "schema_version": conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0],
        "matter": dict(m),
        "standard": {
            "effective": effective_standard(conn, mid),
            "firm_versions": _rows(
                conn, "SELECT * FROM standard WHERE scope='firm' ORDER BY version", ()
            ),
            "matter_versions": _rows(
                conn,
                "SELECT * FROM standard WHERE scope='matter' AND matter_id=? ORDER BY version",
                (mid,),
            ),
        },
        "tables": [],
        "dependencies": _rows(
            conn,
            """SELECT d.*, cf.name AS from_column, rf.name AS from_table, ct.name AS to_column, rt.name AS to_table,
                      sp.name AS parameter_name
               FROM dependency d
               JOIN column_def cf ON cf.id=d.from_column_id JOIN review_table rf ON rf.id=cf.table_id
               JOIN column_def ct ON ct.id=d.to_column_id JOIN review_table rt ON rt.id=ct.table_id
               LEFT JOIN shared_parameter sp ON sp.id=d.parameter_id
               WHERE rf.matter_id=? ORDER BY d.id""",
            (mid,),
        ),
        "parameters": [],
        "document_set_snapshots": _rows(
            conn,
            "SELECT * FROM document_set_snapshot WHERE matter_id=? ORDER BY observed_at, id",
            (mid,),
        ),
        "memo_outline": None,
        "memo_outline_history": [],
        "coverage": None,
        "requirements": [],
        "provenance": [],
    }
    for t in conn.execute(
        "SELECT * FROM review_table WHERE matter_id=? ORDER BY position, name", (mid,)
    ):
        tid = int(t["id"])
        tdoc: dict[str, Any] = {
            **dict(t),
            "instructions_versions": _rows(
                conn, "SELECT * FROM table_instructions WHERE table_id=? ORDER BY version", (tid,)
            ),
            "columns": [],
            "runs": [],
        }
        for c in conn.execute(
            "SELECT * FROM column_def WHERE table_id=? ORDER BY position, id", (tid,)
        ):
            cid = int(c["id"])
            tdoc["columns"].append(
                {
                    **dict(c),
                    "configured_options": json.loads(c["configured_options"])
                    if c["configured_options"]
                    else None,
                    "prompt_versions": _rows(
                        conn,
                        "SELECT * FROM prompt_version WHERE column_id=? ORDER BY major, minor",
                        (cid,),
                    ),
                }
            )
        for r in conn.execute("SELECT * FROM run WHERE table_id=? ORDER BY started_at, id", (tid,)):
            rid = int(r["id"])
            tdoc["runs"].append(
                {
                    **dict(r),
                    "snapshot": _rows(
                        conn,
                        """SELECT rs.column_id, c.name AS column_name, pv.version AS prompt_version, rs.instructions_version_id
                           FROM run_snapshot rs JOIN column_def c ON c.id=rs.column_id
                           JOIN prompt_version pv ON pv.id=rs.prompt_version_id WHERE rs.run_id=? ORDER BY c.position""",
                        (rid,),
                    ),
                    "coverage_dimensions": [
                        x["dimension_key"]
                        for x in conn.execute(
                            "SELECT dimension_key FROM run_coverage WHERE run_id=?", (rid,)
                        )
                    ],
                    "eval_results": _rows(
                        conn,
                        "SELECT e.*, c.name AS column_name FROM eval_result e JOIN column_def c ON c.id=e.column_id WHERE e.run_id=? ORDER BY e.id",
                        (rid,),
                    ),
                }
            )
        doc["tables"].append(tdoc)
    for p in conn.execute("SELECT * FROM shared_parameter WHERE matter_id=? ORDER BY name", (mid,)):
        doc["parameters"].append(
            {
                **dict(p),
                "bindings": _rows(
                    conn,
                    """SELECT pb.*, rt.name AS table_name, c.name AS column_name FROM parameter_binding pb
                       JOIN review_table rt ON rt.id=pb.consuming_table_id LEFT JOIN column_def c ON c.id=pb.consuming_column_id
                       WHERE pb.parameter_id=? ORDER BY pb.id""",
                    (int(p["id"]),),
                ),
            }
        )

    def _outline_doc(outline: sqlite3.Row) -> dict[str, Any]:
        sections = []
        for s in conn.execute(
            "SELECT * FROM memo_section WHERE outline_id=? ORDER BY position", (int(outline["id"]),)
        ):
            assertions = []
            for a in conn.execute(
                "SELECT * FROM memo_assertion WHERE section_id=? ORDER BY position", (int(s["id"]),)
            ):
                assertions.append(
                    {
                        **dict(a),
                        "sources": _rows(
                            conn,
                            """SELECT asrc.note, c.name AS column_name, rt.name AS table_name FROM assertion_source asrc
                               JOIN column_def c ON c.id=asrc.column_id JOIN review_table rt ON rt.id=c.table_id
                               WHERE asrc.assertion_id=? ORDER BY asrc.id""",
                            (int(a["id"]),),
                        ),
                    }
                )
            sections.append({**dict(s), "assertions": assertions})
        return {**dict(outline), "sections": sections}

    for o in conn.execute("SELECT * FROM memo_outline WHERE matter_id=? ORDER BY version", (mid,)):
        if int(o["is_current"]):
            doc["memo_outline"] = _outline_doc(o)
        else:
            doc["memo_outline_history"].append(_outline_doc(o))
    if doc["memo_outline"] is not None:
        try:
            cov = coverage.coverage_check(conn, m["name"])
            cov["findings"] = [f.to_dict() for f in cov["findings"]]
            doc["coverage"] = cov
        except PromptGraphError:
            doc["coverage"] = None
    for src in conn.execute(
        "SELECT * FROM requirement_source WHERE matter_id=? ORDER BY id", (mid,)
    ):
        sdoc: dict[str, Any] = {**dict(src), "requirements": []}
        for r in conn.execute(
            "SELECT * FROM requirement WHERE source_id=? ORDER BY position, id",
            (int(src["id"]),),
        ):
            rdoc: dict[str, Any] = {**dict(r), "parts": []}
            for prt in conn.execute(
                "SELECT * FROM requirement_part WHERE requirement_id=? ORDER BY position",
                (int(r["id"]),),
            ):
                rdoc["parts"].append(
                    {
                        **dict(prt),
                        "links": _rows(
                            conn,
                            """SELECT rl.kind, rl.note, rt.name AS table_name, ms.name AS section_name
                               FROM requirement_link rl
                               LEFT JOIN review_table rt ON rt.id=rl.table_id
                               LEFT JOIN memo_section ms ON ms.id=rl.section_id
                               WHERE rl.part_id=? ORDER BY rl.id""",
                            (int(prt["id"]),),
                        ),
                    }
                )
            sdoc["requirements"].append(rdoc)
        doc["requirements"].append(sdoc)
    doc["provenance"] = _rows(
        conn,
        """SELECT * FROM provenance WHERE
             (entity_type='matter' AND entity_id=?)
          OR (entity_type='table' AND entity_id IN (SELECT id FROM review_table WHERE matter_id=?))
          OR (entity_type='column' AND entity_id IN (SELECT c.id FROM column_def c JOIN review_table rt ON rt.id=c.table_id WHERE rt.matter_id=?))
          OR (entity_type='table_instructions' AND entity_id IN (SELECT ti.id FROM table_instructions ti JOIN review_table rt ON rt.id=ti.table_id WHERE rt.matter_id=?))
          OR (entity_type='parameter' AND entity_id IN (SELECT id FROM shared_parameter WHERE matter_id=?))
          OR (entity_type='run' AND entity_id IN (SELECT r.id FROM run r JOIN review_table rt ON rt.id=r.table_id WHERE rt.matter_id=?))
          OR (entity_type='memo_outline' AND entity_id IN (SELECT id FROM memo_outline WHERE matter_id=?))
          OR (entity_type='document_set_snapshot' AND entity_id IN (SELECT id FROM document_set_snapshot WHERE matter_id=?))
           ORDER BY at, id""",
        (mid,) * 8,
    )
    return doc


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "matter"


def matter_export(
    conn: sqlite3.Connection,
    matter: str,
    write_to: str | None = None,
    inline: bool = False,
) -> dict[str, Any]:
    doc = build_export(conn, matter)
    counts = {
        "tables": len(doc["tables"]),
        "columns": sum(len(t["columns"]) for t in doc["tables"]),
        "prompt_versions": sum(
            len(c["prompt_versions"]) for t in doc["tables"] for c in t["columns"]
        ),
        "runs": sum(len(t["runs"]) for t in doc["tables"]),
        "eval_results": sum(len(r["eval_results"]) for t in doc["tables"] for r in t["runs"]),
        "parameters": len(doc["parameters"]),
        "dependencies": len(doc["dependencies"]),
        "document_set_snapshots": len(doc["document_set_snapshots"]),
        "provenance_events": len(doc["provenance"]),
        "requirements": sum(len(s["requirements"]) for s in doc["requirements"]),
    }
    out: dict[str, Any] = {
        "matter": doc["matter"]["name"],
        "export_format_version": EXPORT_FORMAT_VERSION,
        "exported_at": doc["exported_at"],
        "counts": counts,
        "findings": [],
    }
    if inline:
        out["document"] = doc
        return out
    if write_to:
        target = Path(write_to).expanduser()
        if target.is_dir():
            target = (
                target
                / f"{_slug(doc['matter']['name'])}-{doc['exported_at'][:19].replace(':', '')}.json"
            )
    else:
        target = (
            db_path().parent
            / "exports"
            / f"{_slug(doc['matter']['name'])}-{doc['exported_at'][:19].replace(':', '')}.json"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, indent=1, default=str)
    target.write_text(payload)
    out["path"] = str(target)
    out["bytes"] = len(payload)
    return out
