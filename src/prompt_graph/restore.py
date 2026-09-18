"""Matter import: the inverse of `matter_export`.

Rebuilds a whole matter from an export document. This exists because a matter authored through
chat has no other source: the corpus library can be rebuilt from its markdown, but a suite
written interactively lives in exactly one database file, and until now `matter_export` was
one-way, so that file was the only copy.

Ids are not preserved. Everything that crosses a table boundary in the export is carried by
name (table, column, parameter, memo section), and the few raw ids that remain in the document
are remapped through the maps built while inserting. A provenance row whose subject is absent
from the document keeps its record with a null subject rather than being dropped or, worse,
pointed at whatever now holds the old id.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .db import now
from .export import EXPORT_FORMAT_VERSION
from .findings import PromptGraphError

# Entity types whose provenance can be remapped onto the new rows.
_PROVENANCE_MAPPED = {
    "matter": "matter",
    "table": "table",
    "column": "column",
    "table_instructions": "instructions",
    "parameter": "parameter",
    "run": "run",
    "memo_outline": "outline",
    "document_set_snapshot": "docset",
}


def _load(path: str | None, document: dict[str, Any] | None) -> dict[str, Any]:
    if (path is None) == (document is None):
        raise PromptGraphError("Pass exactly one of path or document.")
    if document is not None:
        return document
    target = Path(str(path)).expanduser()
    if not target.exists():
        raise PromptGraphError(f"No export file at {target}")
    try:
        return json.loads(target.read_text())
    except json.JSONDecodeError as e:
        raise PromptGraphError(f"{target} is not valid JSON: {e}") from e


def _delete_matter(conn: sqlite3.Connection, mid: int) -> None:
    """Children first. No schema-level cascade exists, so the order here is the contract."""
    conn.execute(
        """DELETE FROM assertion_source WHERE assertion_id IN
             (SELECT a.id FROM memo_assertion a JOIN memo_section s ON s.id=a.section_id
              JOIN memo_outline o ON o.id=s.outline_id WHERE o.matter_id=?)""",
        (mid,),
    )
    conn.execute(
        """DELETE FROM requirement_link WHERE part_id IN
             (SELECT p.id FROM requirement_part p JOIN requirement r ON r.id=p.requirement_id
              JOIN requirement_source rs ON rs.id=r.source_id WHERE rs.matter_id=?)""",
        (mid,),
    )
    conn.execute(
        """DELETE FROM requirement_part WHERE requirement_id IN
             (SELECT r.id FROM requirement r JOIN requirement_source rs ON rs.id=r.source_id
              WHERE rs.matter_id=?)""",
        (mid,),
    )
    conn.execute(
        "DELETE FROM requirement WHERE source_id IN (SELECT id FROM requirement_source WHERE matter_id=?)",
        (mid,),
    )
    conn.execute("DELETE FROM requirement_source WHERE matter_id=?", (mid,))
    conn.execute(
        """DELETE FROM memo_assertion WHERE section_id IN
             (SELECT s.id FROM memo_section s JOIN memo_outline o ON o.id=s.outline_id WHERE o.matter_id=?)""",
        (mid,),
    )
    conn.execute(
        "DELETE FROM memo_section WHERE outline_id IN (SELECT id FROM memo_outline WHERE matter_id=?)",
        (mid,),
    )
    conn.execute("DELETE FROM memo_outline WHERE matter_id=?", (mid,))
    runs = "(SELECT r.id FROM run r JOIN review_table rt ON rt.id=r.table_id WHERE rt.matter_id=?)"
    conn.execute(f"DELETE FROM eval_result WHERE run_id IN {runs}", (mid,))
    conn.execute(f"DELETE FROM run_coverage WHERE run_id IN {runs}", (mid,))
    conn.execute(f"DELETE FROM run_snapshot WHERE run_id IN {runs}", (mid,))
    conn.execute(
        "DELETE FROM run WHERE table_id IN (SELECT id FROM review_table WHERE matter_id=?)", (mid,)
    )
    conn.execute(
        "DELETE FROM parameter_binding WHERE parameter_id IN (SELECT id FROM shared_parameter WHERE matter_id=?)",
        (mid,),
    )
    conn.execute("DELETE FROM shared_parameter WHERE matter_id=?", (mid,))
    cols = """(SELECT c.id FROM column_def c JOIN review_table rt ON rt.id=c.table_id WHERE rt.matter_id=?)"""
    conn.execute(f"DELETE FROM dependency WHERE from_column_id IN {cols}", (mid,))
    conn.execute(f"DELETE FROM dependency WHERE to_column_id IN {cols}", (mid,))
    conn.execute(f"DELETE FROM prompt_version WHERE column_id IN {cols}", (mid,))
    conn.execute(
        "DELETE FROM column_def WHERE table_id IN (SELECT id FROM review_table WHERE matter_id=?)",
        (mid,),
    )
    conn.execute(
        "DELETE FROM table_instructions WHERE table_id IN (SELECT id FROM review_table WHERE matter_id=?)",
        (mid,),
    )
    conn.execute("DELETE FROM review_table WHERE matter_id=?", (mid,))
    conn.execute("DELETE FROM document_set_snapshot WHERE matter_id=?", (mid,))
    conn.execute("DELETE FROM standard WHERE scope='matter' AND matter_id=?", (mid,))
    conn.execute("DELETE FROM matter WHERE id=?", (mid,))


def _ins(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
    return int(cur.lastrowid or 0)


def matter_import(
    conn: sqlite3.Connection,
    path: str | None = None,
    document: dict[str, Any] | None = None,
    as_matter: str | None = None,
    replace: bool = False,
    actor: str | None = None,
) -> dict[str, Any]:
    doc = _load(path, document)
    fmt = int(doc.get("export_format_version") or 0)
    if fmt < 1 or fmt > EXPORT_FORMAT_VERSION:
        raise PromptGraphError(
            f"Export format version {fmt} is not readable by this build "
            f"(supports 1 to {EXPORT_FORMAT_VERSION})."
        )
    src_matter = dict(doc["matter"])
    name = as_matter or str(src_matter["name"])

    existing = conn.execute("SELECT id FROM matter WHERE name=?", (name,)).fetchone()
    if existing is not None and not replace:
        raise PromptGraphError(
            f"Matter '{name}' already exists. Pass as_matter to import under a different name, "
            f"or replace=True to overwrite it."
        )

    ts = now()
    conn.execute("BEGIN")
    try:
        if existing is not None:
            _delete_matter(conn, int(existing["id"]))

        mid = _ins(
            conn,
            "matter",
            {
                "name": name,
                "objective": src_matter.get("objective"),
                "side": src_matter.get("side"),
                "status": src_matter.get("status") or "active",
                "created_at": src_matter.get("created_at") or ts,
                "vault_project_id": src_matter.get("vault_project_id"),
            },
        )

        # Firm-scoped standard rows are global and already present; only the matter overlay moves.
        for st in doc.get("standard", {}).get("matter_versions", []) or []:
            row = {k: v for k, v in st.items() if k != "id"}
            row["matter_id"] = mid
            _ins(conn, "standard", row)

        docset: dict[int, int] = {}
        for snap in doc.get("document_set_snapshots", []) or []:
            row = {k: v for k, v in snap.items() if k != "id"}
            row["matter_id"] = mid
            docset[int(snap["id"])] = _ins(conn, "document_set_snapshot", row)

        tables: dict[str, int] = {}
        instructions: dict[int, int] = {}
        columns: dict[tuple[str, str], int] = {}
        versions: dict[tuple[int, str], int] = {}
        runs: list[int] = []
        evals = 0

        for t in doc.get("tables", []) or []:
            trow = {
                k: v
                for k, v in t.items()
                if k not in ("id", "instructions_versions", "columns", "runs")
            }
            trow["matter_id"] = mid
            tid = _ins(conn, "review_table", trow)
            tables[str(t["name"])] = tid
            for iv in t.get("instructions_versions", []) or []:
                row = {k: v for k, v in iv.items() if k != "id"}
                row["table_id"] = tid
                instructions[int(iv["id"])] = _ins(conn, "table_instructions", row)
            for c in t.get("columns", []) or []:
                crow = {k: v for k, v in c.items() if k not in ("id", "prompt_versions")}
                crow["table_id"] = tid
                opts = crow.get("configured_options")
                crow["configured_options"] = json.dumps(opts) if isinstance(opts, list) else opts
                cid = _ins(conn, "column_def", crow)
                columns[(str(t["name"]), str(c["name"]))] = cid
                for pv in c.get("prompt_versions", []) or []:
                    row = {k: v for k, v in pv.items() if k != "id"}
                    row["column_id"] = cid
                    versions[(cid, str(pv["version"]))] = _ins(conn, "prompt_version", row)

        # Runs need the column and version maps, so they come after every table is in.
        for t in doc.get("tables", []) or []:
            tid = tables[str(t["name"])]
            for r in t.get("runs", []) or []:
                rrow = {
                    k: v
                    for k, v in r.items()
                    if k not in ("id", "snapshot", "coverage_dimensions", "eval_results")
                }
                rrow["table_id"] = tid
                old_ds = r.get("document_set_snapshot_id")
                rrow["document_set_snapshot_id"] = docset.get(int(old_ds)) if old_ds else None
                rid = _ins(conn, "run", rrow)
                runs.append(rid)
                for sn in r.get("snapshot", []) or []:
                    cid = columns.get((str(t["name"]), str(sn["column_name"])))
                    pvid = versions.get((cid, str(sn["prompt_version"]))) if cid else None
                    if cid is None or pvid is None:
                        continue
                    old_iv = sn.get("instructions_version_id")
                    conn.execute(
                        """INSERT INTO run_snapshot (run_id, column_id, prompt_version_id, instructions_version_id)
                           VALUES (?,?,?,?)""",
                        (rid, cid, pvid, instructions.get(int(old_iv)) if old_iv else None),
                    )
                for key in r.get("coverage_dimensions", []) or []:
                    conn.execute(
                        "INSERT OR IGNORE INTO run_coverage (run_id, dimension_key) VALUES (?,?)",
                        (rid, key),
                    )
                for ev in r.get("eval_results", []) or []:
                    cid = columns.get((str(t["name"]), str(ev.get("column_name"))))
                    if cid is None:
                        continue
                    row = {k: v for k, v in ev.items() if k not in ("id", "column_name", "run_id")}
                    row["run_id"] = rid
                    row["column_id"] = cid
                    _ins(conn, "eval_result", row)
                    evals += 1

        params: dict[str, int] = {}
        for p in doc.get("parameters", []) or []:
            prow = {k: v for k, v in p.items() if k not in ("id", "bindings")}
            prow["matter_id"] = mid
            prow["source_table_id"] = None
            prow["source_column_id"] = None
            pid = _ins(conn, "shared_parameter", prow)
            params[str(p["name"])] = pid
            for b in p.get("bindings", []) or []:
                btid = tables.get(str(b.get("table_name")))
                if btid is None:
                    continue
                bcid = (
                    columns.get((str(b.get("table_name")), str(b.get("column_name"))))
                    if b.get("column_name")
                    else None
                )
                conn.execute(
                    """INSERT OR IGNORE INTO parameter_binding
                       (parameter_id, consuming_table_id, consuming_column_id, binding_site)
                       VALUES (?,?,?,?)""",
                    (pid, btid, bcid, b["binding_site"]),
                )

        deps = 0
        for d in doc.get("dependencies", []) or []:
            f = columns.get((str(d["from_table"]), str(d["from_column"])))
            to = columns.get((str(d["to_table"]), str(d["to_column"])))
            if f is None or to is None:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO dependency
                   (from_column_id, to_column_id, kind, declared_by, parameter_id, note)
                   VALUES (?,?,?,?,?,?)""",
                (
                    f,
                    to,
                    d["kind"],
                    d["declared_by"],
                    params.get(str(d.get("parameter_name"))) if d.get("parameter_name") else None,
                    d.get("note"),
                ),
            )
            deps += 1

        sections: dict[str, int] = {}
        outlines: dict[int, int] = {}
        assertions = 0
        # Superseded outlines first, current last, so `sections` ends up holding the current
        # outline's ids: that is what requirement_link's produces-a-section edges resolve to.
        current = doc.get("memo_outline")
        for outline in [*(doc.get("memo_outline_history") or []), *([current] if current else [])]:
            orow = {k: v for k, v in outline.items() if k not in ("id", "sections")}
            orow["matter_id"] = mid
            this_outline = _ins(conn, "memo_outline", orow)
            outlines[int(outline["id"])] = this_outline
            for s in outline.get("sections", []) or []:
                srow = {k: v for k, v in s.items() if k not in ("id", "outline_id", "assertions")}
                srow["outline_id"] = this_outline
                sid = _ins(conn, "memo_section", srow)
                sections[str(s["name"])] = sid
                for a in s.get("assertions", []) or []:
                    arow = {k: v for k, v in a.items() if k not in ("id", "section_id", "sources")}
                    arow["section_id"] = sid
                    aid = _ins(conn, "memo_assertion", arow)
                    assertions += 1
                    for srcref in a.get("sources", []) or []:
                        cid = columns.get(
                            (str(srcref.get("table_name")), str(srcref.get("column_name")))
                        )
                        if cid is None:
                            continue
                        conn.execute(
                            "INSERT OR IGNORE INTO assertion_source (assertion_id, column_id, note) VALUES (?,?,?)",
                            (aid, cid, srcref.get("note")),
                        )

        reqs = 0
        for src in doc.get("requirements", []) or []:
            srow = {k: v for k, v in src.items() if k not in ("id", "requirements")}
            srow["matter_id"] = mid
            sid = _ins(conn, "requirement_source", srow)
            for r in src.get("requirements", []) or []:
                rrow = {k: v for k, v in r.items() if k not in ("id", "source_id", "parts")}
                rrow["source_id"] = sid
                rid = _ins(conn, "requirement", rrow)
                reqs += 1
                for prt in r.get("parts", []) or []:
                    prow = {
                        k: v for k, v in prt.items() if k not in ("id", "requirement_id", "links")
                    }
                    prow["requirement_id"] = rid
                    pid = _ins(conn, "requirement_part", prow)
                    for lk in prt.get("links", []) or []:
                        conn.execute(
                            """INSERT OR IGNORE INTO requirement_link
                               (part_id, kind, table_id, section_id, note) VALUES (?,?,?,?,?)""",
                            (
                                pid,
                                lk["kind"],
                                tables.get(str(lk.get("table_name")))
                                if lk.get("table_name")
                                else None,
                                sections.get(str(lk.get("section_name")))
                                if lk.get("section_name")
                                else None,
                                lk.get("note"),
                            ),
                        )

        # Remapped, never id-reused: attaching an event to whatever now holds the old id would
        # be worse than losing it. An unmappable subject is counted and skipped. Now that
        # outline history is exported this should be zero, so a non-zero count means the
        # document is missing something rather than being a routine outcome.
        by_old_table = {int(t["id"]): tables[str(t["name"])] for t in doc.get("tables", []) or []}
        by_old_column: dict[int, int] = {}
        by_old_run: dict[int, int] = {}
        for t in doc.get("tables", []) or []:
            for c in t.get("columns", []) or []:
                by_old_column[int(c["id"])] = columns[(str(t["name"]), str(c["name"]))]
        old_runs = [r for t in doc.get("tables", []) or [] for r in t.get("runs", []) or []]
        for old, new in zip(old_runs, runs, strict=False):
            by_old_run[int(old["id"])] = new
        remap: dict[str, dict[int, int]] = {
            "matter": {int(src_matter["id"]): mid},
            "table": by_old_table,
            "column": by_old_column,
            "table_instructions": instructions,
            "parameter": {
                int(p["id"]): params[str(p["name"])]
                for p in doc.get("parameters", []) or []
                if str(p["name"]) in params
            },
            "run": by_old_run,
            "memo_outline": outlines,
            "document_set_snapshot": docset,
        }
        kept = 0
        orphaned = 0
        for ev in doc.get("provenance", []) or []:
            et = str(ev.get("entity_type"))
            if et not in _PROVENANCE_MAPPED:
                continue
            old_id = ev.get("entity_id")
            new_id = remap.get(et, {}).get(int(old_id)) if old_id is not None else None
            if old_id is not None and new_id is None:
                orphaned += 1
                continue
            _ins(
                conn,
                "provenance",
                {
                    "entity_type": et,
                    "entity_id": new_id,
                    "action": ev.get("action"),
                    "source_type": ev.get("source_type"),
                    "actor": ev.get("actor"),
                    "at": ev.get("at"),
                    "detail": ev.get("detail"),
                },
            )
            kept += 1

        _ins(
            conn,
            "provenance",
            {
                "entity_type": "matter",
                "entity_id": mid,
                "action": "import",
                "source_type": "chat",
                "actor": actor,
                "at": ts,
                "detail": json.dumps(
                    {
                        "export_format_version": fmt,
                        "exported_at": doc.get("exported_at"),
                        "from_name": src_matter.get("name"),
                        "replaced": existing is not None,
                        "provenance_kept": kept,
                    }
                ),
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return {
        "matter": name,
        "replaced": existing is not None,
        "export_format_version": fmt,
        "exported_at": doc.get("exported_at"),
        "counts": {
            "tables": len(tables),
            "columns": len(columns),
            "prompt_versions": len(versions),
            "dependencies": deps,
            "parameters": len(params),
            "runs": len(runs),
            "eval_results": evals,
            "memo_sections": len(sections),
            "memo_assertions": assertions,
            "requirements": reqs,
            "document_set_snapshots": len(docset),
            "provenance_events": kept,
            "provenance_orphaned": orphaned,
        },
        "findings": [],
    }
