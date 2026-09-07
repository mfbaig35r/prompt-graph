"""The dependency graph over every column in a matter, across tables.

Three edge kinds (requirements §6): `intra_table_ref` (a real Harvey @Column),
`cross_table_parameter` (mediated by a shared parameter), `advisory` (a real analytical
dependency Harvey cannot express). Traversals never loop: every walk carries a visited set,
and ordering falls back gracefully when a cycle prevents a topological sort.
"""

from __future__ import annotations

import heapq
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .findings import Finding


@dataclass(slots=True)
class Node:
    id: int
    name: str
    table_id: int
    table_name: str
    table_position: int
    position: int
    status: str
    native_type: str
    role: str | None


@dataclass(slots=True)
class Edge:
    src: int
    dst: int
    kind: str
    parameter_id: int | None
    parameter_name: str | None = None


@dataclass(slots=True)
class Graph:
    nodes: dict[int, Node] = field(default_factory=dict)
    out: dict[int, list[Edge]] = field(default_factory=dict)
    inc: dict[int, list[Edge]] = field(default_factory=dict)

    def sort_key(self, nid: int) -> tuple[int, int]:
        n = self.nodes[nid]
        return (n.table_position, n.position)


def load_graph(conn: sqlite3.Connection, matter_id: int, include_retired: bool = True) -> Graph:
    g = Graph()
    rows = conn.execute(
        """SELECT c.id, c.name, c.table_id, rt.name AS table_name, COALESCE(rt.position, 0) AS tpos,
                  c.position, c.status, c.native_type, c.role
           FROM column_def c JOIN review_table rt ON rt.id=c.table_id WHERE rt.matter_id=?""",
        (matter_id,),
    ).fetchall()
    for r in rows:
        if not include_retired and r["status"] == "retired":
            continue
        g.nodes[int(r["id"])] = Node(
            int(r["id"]),
            r["name"],
            int(r["table_id"]),
            r["table_name"],
            int(r["tpos"]),
            int(r["position"]),
            r["status"],
            r["native_type"],
            r["role"],
        )
        g.out[int(r["id"])] = []
        g.inc[int(r["id"])] = []
    edges = conn.execute(
        """SELECT d.from_column_id, d.to_column_id, d.kind, d.parameter_id, sp.name AS pname
           FROM dependency d
           JOIN column_def cf ON cf.id=d.from_column_id JOIN review_table rf ON rf.id=cf.table_id
           LEFT JOIN shared_parameter sp ON sp.id=d.parameter_id
           WHERE rf.matter_id=?""",
        (matter_id,),
    ).fetchall()
    for e in edges:
        s, d = int(e["from_column_id"]), int(e["to_column_id"])
        if s not in g.nodes or d not in g.nodes:
            continue
        edge = Edge(s, d, e["kind"], e["parameter_id"], e["pname"])
        g.out[s].append(edge)
        g.inc[d].append(edge)
    return g


# ---------------------------------------------------------------------------
# Cycles and ordering
# ---------------------------------------------------------------------------


def find_cycles(g: Graph) -> list[list[int]]:
    """Every elementary cycle reachable in the graph, as lists of node ids (Johnson-lite via DFS)."""
    cycles: list[list[int]] = []
    seen_sets: set[frozenset[int]] = set()
    color: dict[int, int] = {}
    stack: list[int] = []

    def dfs(u: int) -> None:
        color[u] = 1
        stack.append(u)
        for e in g.out.get(u, []):
            v = e.dst
            c = color.get(v, 0)
            if c == 0:
                dfs(v)
            elif c == 1:
                cyc = stack[stack.index(v) :]
                key = frozenset(cyc)
                if key not in seen_sets:
                    seen_sets.add(key)
                    cycles.append(list(cyc))
        stack.pop()
        color[u] = 2

    for nid in sorted(g.nodes, key=g.sort_key):
        if color.get(nid, 0) == 0:
            dfs(nid)
    return cycles


def topo_order(g: Graph, subset: set[int]) -> tuple[list[int], list[int]]:
    """Kahn's algorithm over the induced subgraph, always taking the ready node with the
    smallest (table position, column position). Returns (ordered, leftover-in-cycle)."""
    indeg = {n: 0 for n in subset}
    for n in subset:
        for e in g.out.get(n, []):
            if e.dst in subset:
                indeg[e.dst] += 1
    heap: list[tuple[tuple[int, int], int]] = [(g.sort_key(n), n) for n in subset if indeg[n] == 0]
    heapq.heapify(heap)
    ordered: list[int] = []
    while heap:
        _, u = heapq.heappop(heap)
        ordered.append(u)
        for e in g.out.get(u, []):
            if e.dst in subset:
                indeg[e.dst] -= 1
                if indeg[e.dst] == 0:
                    heapq.heappush(heap, (g.sort_key(e.dst), e.dst))
    done = set(ordered)
    leftover = sorted([n for n in subset if n not in done], key=g.sort_key)
    return ordered, leftover


def _cycle_members(g: Graph, subset: set[int]) -> set[int]:
    """Nodes of `subset` that lie on a cycle within the induced subgraph."""
    sub = Graph(nodes={n: g.nodes[n] for n in subset})
    for n in subset:
        sub.out[n] = [e for e in g.out.get(n, []) if e.dst in subset]
        sub.inc[n] = [e for e in g.inc.get(n, []) if e.src in subset]
    return {n for cyc in find_cycles(sub) for n in cyc}


def downstream_closure(g: Graph, roots: list[int]) -> dict[int, dict[str, Any]]:
    """BFS downstream from roots. Value: {'direct': bool, 'via': [(from_id, kind, param)]}."""
    hit: dict[int, dict[str, Any]] = {}
    q: deque[int] = deque()
    rootset = set(roots)
    for r in roots:
        for e in g.out.get(r, []):
            if e.dst in rootset:
                continue
            if e.dst not in hit:
                hit[e.dst] = {"direct": True, "via": []}
                q.append(e.dst)
            hit[e.dst]["via"].append((e.src, e.kind, e.parameter_name))
    visited = set(hit)
    while q:
        u = q.popleft()
        for e in g.out.get(u, []):
            v = e.dst
            if v in rootset:
                continue
            if v not in hit:
                hit[v] = {"direct": False, "via": []}
            hit[v]["via"].append((e.src, e.kind, e.parameter_name))
            if v not in visited:
                visited.add(v)
                q.append(v)
    return hit


def upstream_closure(g: Graph, root: int) -> set[int]:
    seen: set[int] = set()
    q: deque[int] = deque([root])
    while q:
        u = q.popleft()
        for e in g.inc.get(u, []):
            if e.src not in seen and e.src != root:
                seen.add(e.src)
                q.append(e.src)
    return seen


# ---------------------------------------------------------------------------
# Impact of change
# ---------------------------------------------------------------------------


def _node_dict(g: Graph, nid: int) -> dict[str, Any]:
    n = g.nodes[nid]
    return {
        "column_id": n.id,
        "column": n.name,
        "table": n.table_name,
        "native_type": n.native_type,
        "status": n.status,
    }


def impact_of_column(conn: sqlite3.Connection, matter_id: int, column_id: int) -> dict[str, Any]:
    g = load_graph(conn, matter_id)
    if column_id not in g.nodes:
        raise KeyError(column_id)
    hit = downstream_closure(g, [column_id])
    subset = set(hit) | {column_id}
    ordered, leftover = topo_order(g, subset)
    cycle_nodes = _cycle_members(g, subset)
    findings: list[Finding] = []
    if leftover:
        cyc_names = [
            f"{g.nodes[n].table_name} / {g.nodes[n].name}" for n in leftover if n in cycle_nodes
        ]
        findings.append(
            Finding(
                "GRAPH_CYCLE",
                "column",
                column_id,
                g.nodes[column_id].name,
                "The downstream set contains a dependency cycle, so part of the rerun order is undetermined.",
                {"columns_in_cycle": cyc_names},
            )
        )
    sequence: list[dict[str, Any]] = []
    for nid in ordered + leftover:
        if nid == column_id:
            continue
        info = hit[nid]
        d = _node_dict(g, nid)
        d["impact"] = "direct" if info["direct"] else "transitive"
        d["via"] = [
            {
                "from": g.nodes[s].name,
                "from_table": g.nodes[s].table_name,
                "kind": k,
                "parameter": p,
            }
            for s, k, p in info["via"]
        ]
        d["in_cycle"] = nid in cycle_nodes
        sequence.append(d)
    tables: dict[str, int] = {}
    for s in sequence:
        tables[s["table"]] = tables.get(s["table"], 0) + 1
    return {
        "subject": _node_dict(g, column_id),
        "affected_count": len(sequence),
        "direct_count": sum(1 for s in sequence if s["impact"] == "direct"),
        "transitive_count": sum(1 for s in sequence if s["impact"] == "transitive"),
        "tables_affected": tables,
        "rerun_sequence": sequence,
        "findings": findings,
    }


def impact_of_parameter(
    conn: sqlite3.Connection, matter_id: int, parameter: sqlite3.Row, new_value: str | None = None
) -> dict[str, Any]:
    from .service import current_instructions, current_prompt, table_columns

    g = load_graph(conn, matter_id)
    pid = int(parameter["id"])
    bindings = conn.execute(
        """SELECT pb.*, rt.name AS table_name, c.name AS column_name FROM parameter_binding pb
           JOIN review_table rt ON rt.id=pb.consuming_table_id
           LEFT JOIN column_def c ON c.id=pb.consuming_column_id
           WHERE pb.parameter_id=? ORDER BY rt.position, c.position""",
        (pid,),
    ).fetchall()
    old_value = parameter["value"]
    consumers: list[dict[str, Any]] = []
    roots: list[int] = []
    text_sites: list[dict[str, Any]] = []
    for b in bindings:
        entry = {"table": b["table_name"], "column": b["column_name"], "site": b["binding_site"]}
        consumers.append(entry)
        if b["consuming_column_id"] is not None:
            roots.append(int(b["consuming_column_id"]))
        else:
            roots.extend(int(c["id"]) for c in table_columns(conn, int(b["consuming_table_id"])))
        # Where the old value is written down and would need editing.
        if old_value:
            if b["binding_site"] == "table_instructions":
                ti = current_instructions(conn, int(b["consuming_table_id"]))
                if ti and old_value.lower() in ti["text"].lower():
                    text_sites.append(
                        {
                            "table": b["table_name"],
                            "site": "table_instructions",
                            "version": int(ti["version"]),
                            "occurrences": ti["text"].lower().count(old_value.lower()),
                        }
                    )
            elif b["consuming_column_id"] is not None:
                pv = current_prompt(conn, int(b["consuming_column_id"]))
                if pv and old_value.lower() in pv["text"].lower():
                    text_sites.append(
                        {
                            "table": b["table_name"],
                            "column": b["column_name"],
                            "site": "column_prompt",
                            "version": pv["version"],
                            "occurrences": pv["text"].lower().count(old_value.lower()),
                        }
                    )
    # Any prompt or instructions in the matter that contains the old value but is not bound.
    if old_value:
        bound_tables = {
            b["consuming_table_id"] for b in bindings if b["binding_site"] == "table_instructions"
        }
        bound_cols = {
            b["consuming_column_id"] for b in bindings if b["consuming_column_id"] is not None
        }
        for t in conn.execute("SELECT * FROM review_table WHERE matter_id=?", (matter_id,)):
            ti = current_instructions(conn, int(t["id"]))
            if ti and int(t["id"]) not in bound_tables and old_value.lower() in ti["text"].lower():
                text_sites.append(
                    {
                        "table": t["name"],
                        "site": "table_instructions",
                        "version": int(ti["version"]),
                        "occurrences": ti["text"].lower().count(old_value.lower()),
                        "unbound": True,
                    }
                )
            for c in table_columns(conn, int(t["id"])):
                if int(c["id"]) in bound_cols:
                    continue
                pv = current_prompt(conn, int(c["id"]))
                if pv and old_value.lower() in pv["text"].lower():
                    text_sites.append(
                        {
                            "table": t["name"],
                            "column": c["name"],
                            "site": "column_prompt",
                            "version": pv["version"],
                            "occurrences": pv["text"].lower().count(old_value.lower()),
                            "unbound": True,
                        }
                    )

    roots = sorted(set(r for r in roots if r in g.nodes), key=g.sort_key)
    hit = downstream_closure(g, roots)
    subset = set(hit) | set(roots)
    ordered, leftover = topo_order(g, subset)
    cycle_nodes = _cycle_members(g, subset)
    findings: list[Finding] = []
    if leftover:
        findings.append(
            Finding(
                "GRAPH_CYCLE",
                "parameter",
                pid,
                parameter["name"],
                "The downstream set contains a dependency cycle, so part of the rerun order is undetermined.",
                {
                    "columns_in_cycle": [
                        f"{g.nodes[n].table_name} / {g.nodes[n].name}"
                        for n in leftover
                        if n in cycle_nodes
                    ]
                },
            )
        )
    sequence: list[dict[str, Any]] = []
    rootset = set(roots)
    for nid in ordered + leftover:
        d = _node_dict(g, nid)
        if nid in rootset:
            d["impact"] = "direct"
            d["via"] = [{"parameter": parameter["name"]}]
        else:
            d["impact"] = "transitive"
            d["via"] = [
                {
                    "from": g.nodes[s].name,
                    "from_table": g.nodes[s].table_name,
                    "kind": k,
                    "parameter": p,
                }
                for s, k, p in hit[nid]["via"]
            ]
        d["in_cycle"] = nid in cycle_nodes
        sequence.append(d)
    tables: dict[str, int] = {}
    for s in sequence:
        tables[s["table"]] = tables.get(s["table"], 0) + 1
    return {
        "subject": {
            "parameter": parameter["name"],
            "value": old_value,
            "status": parameter["status"],
            "new_value": new_value,
        },
        "consumers": consumers,
        "text_sites_containing_current_value": text_sites,
        "affected_count": len(sequence),
        "direct_count": sum(1 for s in sequence if s["impact"] == "direct"),
        "transitive_count": sum(1 for s in sequence if s["impact"] == "transitive"),
        "tables_affected": tables,
        "rerun_sequence": sequence,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def _last_runs(conn: sqlite3.Connection, matter_id: int) -> dict[int, sqlite3.Row]:
    """Latest run snapshot row per column (by run.started_at, then run id)."""
    rows = conn.execute(
        """SELECT rs.column_id, rs.prompt_version_id, rs.instructions_version_id, r.id AS run_id,
                  r.started_at, r.table_id
           FROM run_snapshot rs JOIN run r ON r.id=rs.run_id
           JOIN review_table rt ON rt.id=r.table_id
           WHERE rt.matter_id=? ORDER BY r.started_at, r.id""",
        (matter_id,),
    ).fetchall()
    out: dict[int, sqlite3.Row] = {}
    for r in rows:
        out[int(r["column_id"])] = r  # later rows overwrite: last wins
    return out


def staleness_map(conn: sqlite3.Connection, matter_id: int) -> dict[int, dict[str, Any]]:
    """Per column: state ∈ never_run | current | direct | transitive, with reasons."""
    g = load_graph(conn, matter_id, include_retired=False)
    last = _last_runs(conn, matter_id)
    cur_pv = {
        int(r["column_id"]): r
        for r in conn.execute(
            """SELECT pv.* FROM prompt_version pv JOIN column_def c ON c.id=pv.column_id
               JOIN review_table rt ON rt.id=c.table_id WHERE rt.matter_id=? AND pv.is_current=1""",
            (matter_id,),
        )
    }
    cur_ti = {
        int(r["table_id"]): r
        for r in conn.execute(
            """SELECT ti.* FROM table_instructions ti JOIN review_table rt ON rt.id=ti.table_id
               WHERE rt.matter_id=? AND ti.is_current=1""",
            (matter_id,),
        )
    }
    # Parameter bindings by column (direct) and by table (fan-out), with resolved_at.
    pbind = conn.execute(
        """SELECT pb.consuming_table_id, pb.consuming_column_id, sp.name, sp.resolved_at
           FROM parameter_binding pb JOIN shared_parameter sp ON sp.id=pb.parameter_id
           WHERE sp.matter_id=?""",
        (matter_id,),
    ).fetchall()

    result: dict[int, dict[str, Any]] = {}
    for nid, n in g.nodes.items():
        lr = last.get(nid)
        if lr is None:
            result[nid] = {"state": "never_run", "reasons": [], "last_run": None}
            continue
        reasons: list[str] = []
        pv = cur_pv.get(nid)
        if pv is not None and int(pv["id"]) != int(lr["prompt_version_id"]):
            old = conn.execute(
                "SELECT version FROM prompt_version WHERE id=?", (lr["prompt_version_id"],)
            ).fetchone()
            reasons.append(
                f"prompt version changed ({old['version'] if old else '?'} → {pv['version']}) after the last run"
            )
        ti = cur_ti.get(n.table_id)
        if ti is not None and (
            lr["instructions_version_id"] is None
            or int(ti["id"]) != int(lr["instructions_version_id"])
        ):
            reasons.append(f"table instructions changed (now v{ti['version']}) after the last run")
        for b in pbind:
            if int(b["consuming_table_id"]) != n.table_id:
                continue
            if b["consuming_column_id"] is not None and int(b["consuming_column_id"]) != nid:
                continue
            if b["resolved_at"] and b["resolved_at"] > lr["started_at"]:
                reasons.append(f"shared parameter '{b['name']}' was resolved after the last run")
        result[nid] = {
            "state": "direct" if reasons else "current",
            "reasons": reasons,
            "last_run": {"run_id": int(lr["run_id"]), "started_at": lr["started_at"]},
        }

    # Snapshot prompt-version ids per (run, column) so same-run upstreams compare exactly.
    snap: dict[tuple[int, int], int] = {
        (int(r["run_id"]), int(r["column_id"])): int(r["prompt_version_id"])
        for r in conn.execute(
            """SELECT rs.run_id, rs.column_id, rs.prompt_version_id FROM run_snapshot rs
               JOIN run r ON r.id=rs.run_id JOIN review_table rt ON rt.id=r.table_id WHERE rt.matter_id=?""",
            (matter_id,),
        )
    }

    def upstream_reasons(nid: int) -> list[str]:
        """One reason per upstream edge whose source is stale or changed since this column's run."""
        reasons: list[str] = []
        my_last = last.get(nid)
        for e in g.inc.get(nid, []):
            u = e.src
            if u not in g.nodes:
                continue
            un = g.nodes[u]
            st = result[u]["state"]
            if st in ("direct", "transitive"):
                reasons.append(
                    f"upstream '{un.table_name} / {un.name}' is {st}ly stale (via {e.kind})"
                )
                continue
            upv = cur_pv.get(u)
            if my_last is None or upv is None:
                continue
            key = (int(my_last["run_id"]), u)
            if key in snap:
                if snap[key] != int(upv["id"]):
                    reasons.append(
                        f"upstream '{un.table_name} / {un.name}' changed to {upv['version']} after this column's last run (via {e.kind})"
                    )
            elif upv["created_at"] > my_last["started_at"]:
                reasons.append(
                    f"upstream '{un.table_name} / {un.name}' changed to {upv['version']} after this column's last run (via {e.kind})"
                )
        return reasons

    # Propagate until stable; bounded by node count so a cycle cannot loop forever.
    changed = True
    guard = 0
    while changed and guard <= len(g.nodes) + 1:
        changed = False
        guard += 1
        for nid in sorted(g.nodes, key=g.sort_key):
            if result[nid]["state"] != "current":
                continue
            reasons = upstream_reasons(nid)
            if reasons:
                result[nid]["state"] = "transitive"
                result[nid]["reasons"] = reasons
                changed = True
    return result


def column_staleness(conn: sqlite3.Connection, column_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT rt.matter_id FROM column_def c JOIN review_table rt ON rt.id=c.table_id WHERE c.id=?",
        (column_id,),
    ).fetchone()
    if row is None:
        return None
    return staleness_map(conn, int(row["matter_id"])).get(column_id)


def staleness_report(
    conn: sqlite3.Connection, matter_id: int, table_id: int | None = None
) -> dict[str, Any]:
    g = load_graph(conn, matter_id, include_retired=False)
    smap = staleness_map(conn, matter_id)
    items: list[dict[str, Any]] = []
    counts = {"never_run": 0, "current": 0, "direct": 0, "transitive": 0}
    for nid in sorted(g.nodes, key=g.sort_key):
        n = g.nodes[nid]
        if table_id is not None and n.table_id != table_id:
            continue
        s = smap[nid]
        counts[s["state"]] += 1
        if s["state"] in ("direct", "transitive", "never_run"):
            items.append({**_node_dict(g, nid), **s})
    # Rerun order for the stale set.
    stale_ids = {i["column_id"] for i in items if i["state"] in ("direct", "transitive")}
    ordered, leftover = topo_order(g, stale_ids)
    order = [f"{g.nodes[n].table_name} / {g.nodes[n].name}" for n in ordered + leftover]
    findings: list[Finding] = []
    if leftover:
        cycle_nodes = _cycle_members(g, stale_ids)
        findings.append(
            Finding(
                "GRAPH_CYCLE",
                "matter",
                matter_id,
                "matter",
                "The stale set contains a dependency cycle, so part of the rerun order is undetermined.",
                {
                    "columns_in_cycle": [
                        f"{g.nodes[n].table_name} / {g.nodes[n].name}"
                        for n in leftover
                        if n in cycle_nodes
                    ]
                },
            )
        )
    return {"counts": counts, "stale": items, "rerun_order": order, "findings": findings}
