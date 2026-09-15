"""Read-only HTTP API over the same service functions the MCP tools call.

The MCP server is the only writer. This process opens the database read-only (SQLite refuses
writes on the connection) and never migrates, so running the UI alongside a Claude session
cannot change a client-data database.

Every route is matter-scoped from the start, even while there is one matter, because matter is
where access control will have to go when this is hosted.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import checks as checks_mod
from . import db, overview, readiness, service
from .findings import Finding, PromptGraphError, dump

app = FastAPI(title="prompt-graph read API", version="0.1.0")

# The UI is a separate origin in development. Hosting will put both behind one origin.
# Serving the UI from anywhere but localhost (a LAN address, a tunnel) makes it a new origin,
# and a blocked request shows up as a page stuck on "Loading" with nothing in the API log, so
# the allowed list is configurable rather than something to discover the hard way.
ENV_ORIGINS = "PROMPT_GRAPH_UI_ORIGINS"
DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def allowed_origins() -> list[str]:
    raw = os.environ.get(ENV_ORIGINS, "")
    return [o.strip() for o in raw.split(",") if o.strip()] or list(DEFAULT_ORIGINS)


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@contextmanager
def _conn():
    """One connection per request. A long-lived reader inside an open transaction would pin a
    WAL snapshot and stop reflecting the MCP server's writes."""
    try:
        c = db.connect_readonly()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    try:
        yield c
    finally:
        c.close()


def _serialise(result: dict[str, Any]) -> dict[str, Any]:
    """Findings come back as objects from the service layer; the MCP tool wrapper is what
    normally dumps them. Do the same here so the UI sees one shape."""
    out = dict(result)
    fs = out.get("findings")
    if fs and isinstance(fs[0], Finding):
        out["findings"] = dump(fs)
    out.setdefault("findings", [])
    out["finding_count"] = len(out["findings"])
    return out


@app.get("/api/health")
def health() -> dict[str, Any]:
    with _conn() as c:
        return {
            "ok": True,
            "database": str(db.db_path()),
            "schema_version": db.current_version(c),
            "read_only": True,
        }


# PRAGMA data_version counts commits made by OTHER connections, and the counter belongs to the
# connection. A per-request connection would restart the count every call and never report a
# change, so the watcher is one long-lived reader. It stays in autocommit and never opens a
# transaction, so it does not pin a WAL snapshot and still sees every commit.
_version_conn: sqlite3.Connection | None = None
_version_lock = threading.Lock()


@app.get("/api/version")
def version() -> dict[str, int]:
    """Poll this. `data_version` changes when the MCP server commits, which is the signal to
    refetch the expensive views. Reading it costs one pragma."""
    global _version_conn
    with _version_lock:
        if _version_conn is None:
            try:
                _version_conn = db.connect_readonly(check_same_thread=False)
            except FileNotFoundError as e:
                raise HTTPException(status_code=503, detail=str(e)) from e
        return {"data_version": db.data_version(_version_conn)}


@app.get("/api/matters")
def matters() -> dict[str, Any]:
    with _conn() as c:
        return {"matters": service.list_matters(c)}


@app.get("/api/matters/{matter}")
def matter_detail(matter: str) -> dict[str, Any]:
    with _conn() as c:
        try:
            m = service.get_matter(c, matter)
        except PromptGraphError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return _serialise(overview.matter_overview(c, m))


@app.get("/api/matters/{matter}/concepts")
def concepts(matter: str) -> dict[str, Any]:
    """Where the same legal concept is handled differently in different modules.

    Two consistency checks answer this. CONCEPT_DIVERGENT_RULES finds one column name used in
    several modules with different types, options, or fallback states. CONCEPT_NAME_VARIANT
    finds near-identical names with no shared concept tag. The findings carry the column list;
    this resolves each one back to its type and option set so the divergence can be shown
    rather than asserted, and computes which options every module agrees on.
    """
    with _conn() as c:
        try:
            m = service.get_matter(c, matter)
        except PromptGraphError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        res = checks_mod.suite_check(c, matter, checks=["consistency"])

        def resolve(ref: str) -> dict[str, Any]:
            # Table names carry no " / ", so the first separator splits table from column.
            table, _, column = ref.partition(" / ")
            row = c.execute(
                """SELECT c.name, c.native_type, c.configured_options, c.status, c.role
                   FROM column_def c JOIN review_table rt ON rt.id = c.table_id
                   WHERE rt.matter_id = ? AND rt.name = ? AND c.name = ?""",
                (int(m["id"]), table, column),
            ).fetchone()
            out: dict[str, Any] = {"table": table, "column": column}
            if row:
                out["native_type"] = row["native_type"]
                out["status"] = row["status"]
                out["role"] = row["role"]
                try:
                    out["options"] = json.loads(row["configured_options"] or "null")
                except (ValueError, TypeError):
                    out["options"] = None
            return out

        divergent = []
        for f in res["findings"]:
            if f.code != "CONCEPT_DIVERGENT_RULES":
                continue
            members = [resolve(r) for r in f.evidence.get("columns", [])]
            sets = [set(mm["options"]) for mm in members if mm.get("options")]
            shared = sorted(set.intersection(*sets)) if sets else []
            for mm in members:
                opts = mm.get("options") or []
                mm["divergent_options"] = [o for o in opts if o not in shared]
            distinct_sets = len({tuple(sorted(x)) for x in sets})
            divergent.append(
                {
                    "distinct_option_sets": distinct_sets,
                    "name": members[0]["column"] if members else f.subject_name,
                    "observation": f.observation,
                    "members": members,
                    "shared_options": shared,
                    "native_types": sorted(
                        {mm.get("native_type") for mm in members if mm.get("native_type")}
                    ),
                }
            )
        # Rank by how much they actually differ, not how many modules share the name: one name
        # used in 23 modules with an identical rule everywhere is agreement, not divergence.
        divergent.sort(key=lambda d: (-d["distinct_option_sets"], -len(d["members"])))

        variants = []
        for f in res["findings"]:
            if f.code != "CONCEPT_NAME_VARIANT":
                continue
            members = [resolve(r) for r in f.evidence.get("columns", [])]
            variants.append(
                {
                    "names": f.evidence.get("names") or sorted({mm["column"] for mm in members}),
                    "observation": f.observation,
                    "confidence": f.evidence.get("confidence", "strong"),
                    "reasons": f.evidence.get("confidence_reasons", []),
                    "concept": f.evidence.get("concept"),
                    "members": members,
                    "tables": len({mm["table"] for mm in members}),
                }
            )
        # What to act on first, then what merely warrants a look.
        variants.sort(key=lambda v: (v["confidence"] != "strong", -len(v["names"]), v["names"][0]))
        other = [
            f
            for f in res["findings"]
            if f.code not in ("CONCEPT_DIVERGENT_RULES", "CONCEPT_NAME_VARIANT")
        ]

        # Tagging progress: the heuristic exists only because concepts are untagged, so how much
        # of the matter carries a concept measures how much of this page is still guesswork.
        tagged, total = c.execute(
            """SELECT COUNT(c.concept), COUNT(*) FROM column_def c
               JOIN review_table rt ON rt.id = c.table_id
               WHERE rt.matter_id = ? AND c.retired_at IS NULL""",
            (int(m["id"]),),
        ).fetchone()
        return {
            "matter": m["name"],
            "divergent": divergent,
            "name_variants": variants,
            "other": dump(other),
            "counts": {
                "divergent": len(divergent),
                "name_variants": len(variants),
                "name_variants_strong": sum(1 for v in variants if v["confidence"] == "strong"),
                "other": len(other),
                "tagged_columns": tagged,
                "total_columns": total,
            },
        }


@app.get("/api/matters/{matter}/tables/{table}")
def table_detail(matter: str, table: str) -> dict[str, Any]:
    """A module and every rule in it, with the readiness findings grouped by cause."""
    with _conn() as c:
        try:
            m = service.get_matter(c, matter)
            t = service.get_table(c, int(m["id"]), table)
            cols = service.columns_find(c, matter, table=table, limit=500)
            ready = readiness.table_readiness(c, matter, table)
        except PromptGraphError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {
            "matter": m["name"],
            "table": t["name"],
            "review_unit": t["review_unit"],
            "grouping_enabled": bool(t["grouping_enabled"]),
            "stage": t["stage"],
            "columns": cols["columns"],
            "column_count": cols["total"],
            "readiness": _serialise(ready),
        }


@app.get("/api/matters/{matter}/tables/{table}/graph")
def table_graph(matter: str, table: str) -> dict[str, Any]:
    """The module's reference graph, laid out in layers.

    Every edge is a `@Column` reference parsed from prompt text: `from` is upstream, `to` is
    downstream. A node's level is its longest path from a root, so upstream sits above what
    reads it. Nodes touching no edge are returned too, marked isolated, because hiding them
    would misrepresent how much of the module is actually wired together.
    """
    with _conn() as c:
        try:
            m = service.get_matter(c, matter)
            t = service.get_table(c, int(m["id"]), table)
        except PromptGraphError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        tid = int(t["id"])
        rows = c.execute(
            "SELECT id, name, position, native_type, role, status FROM column_def"
            " WHERE table_id=? AND retired_at IS NULL ORDER BY position",
            (tid,),
        ).fetchall()
        ids = {int(r["id"]) for r in rows}
        edges = [
            {"from": int(e["from_column_id"]), "to": int(e["to_column_id"]), "kind": e["kind"]}
            for e in c.execute(
                "SELECT from_column_id, to_column_id, kind FROM dependency"
            ).fetchall()
            if int(e["from_column_id"]) in ids and int(e["to_column_id"]) in ids
        ]

        upstream: dict[int, list[int]] = {i: [] for i in ids}
        degree: dict[int, int] = dict.fromkeys(ids, 0)
        for e in edges:
            upstream[e["to"]].append(e["from"])
            degree[e["to"]] += 1
            degree[e["from"]] += 1

        level: dict[int, int] = {}

        def lvl(n: int, seen: frozenset[int] = frozenset()) -> int:
            if n in level:
                return level[n]
            if n in seen:  # defensive: the corpus has no cycles, but never loop forever
                return 0
            v = max((lvl(u, seen | {n}) + 1 for u in upstream[n]), default=0)
            level[n] = v
            return v

        nodes = [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "position": r["position"],
                "native_type": r["native_type"],
                "role": r["role"],
                "status": r["status"],
                "level": lvl(int(r["id"])),
                "degree": degree[int(r["id"])],
                "isolated": degree[int(r["id"])] == 0,
            }
            for r in rows
        ]
        return {
            "matter": m["name"],
            "table": t["name"],
            "nodes": nodes,
            "edges": edges,
            "depth": (max((n["level"] for n in nodes), default=0) + 1),
            "linked": sum(1 for n in nodes if not n["isolated"]),
        }


@app.get("/api/matters/{matter}/tables/{table}/columns/{column}")
def column_detail(matter: str, table: str, column: str) -> dict[str, Any]:
    """One rule in full: current prompt text, every prior version, dependencies both ways."""
    with _conn() as c:
        try:
            return service.column_read(c, matter, table, column, include_history=True)
        except PromptGraphError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/api/matters/{matter}/activity")
def activity(matter: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """The provenance log as a feed. Side by side with a Claude session this is what makes the
    model's work legible: each ingest, revision, and parameter resolution lands here."""
    limit = max(1, min(limit, 500))
    with _conn() as c:
        try:
            service.get_matter(c, matter)
        except PromptGraphError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        rows = c.execute(
            "SELECT id, entity_type, entity_id, action, source_type, actor, at, detail"
            " FROM provenance ORDER BY at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = c.execute("SELECT COUNT(*) FROM provenance").fetchone()[0]
        return {
            "events": [_event(c, r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def _event(c: sqlite3.Connection, r: sqlite3.Row) -> dict[str, Any]:
    """Resolve the subject to a name. The log stores ids; a reader needs words."""
    name = None
    et, eid = r["entity_type"], r["entity_id"]
    if eid is not None:
        table = {
            "column": ("column_def", "name"),
            "table": ("review_table", "name"),
            "matter": ("matter", "name"),
            "parameter": ("shared_parameter", "name"),
        }.get(et)
        if table:
            row = c.execute(
                f"SELECT {table[1]} AS n FROM {table[0]} WHERE id=?",  # noqa: S608 (fixed map)
                (eid,),
            ).fetchone()
            name = row["n"] if row else None
    return {
        "id": r["id"],
        "entity_type": et,
        "entity_id": eid,
        "entity_name": name,
        "action": r["action"],
        "source_type": r["source_type"],
        "actor": r["actor"],
        "at": r["at"],
        "detail": r["detail"],
    }


def main() -> None:
    import argparse

    import uvicorn

    p = argparse.ArgumentParser(prog="prompt-graph-api", description="Read-only HTTP API.")
    p.add_argument("--db", help=f"SQLite path (default: ${db.ENV_VAR} or {db.DEFAULT_PATH})")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    a = p.parse_args()
    if a.db:
        os.environ[db.ENV_VAR] = a.db
    uvicorn.run(app, host=a.host, port=a.port)
