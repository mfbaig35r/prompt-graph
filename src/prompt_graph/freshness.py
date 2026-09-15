"""Source freshness (Addendum A.1): has the document set moved since a column last ran?

A run records which prompt versions executed. A document-set snapshot records what they
executed against: how many ready_to_query files a Vault project held, the latest upload,
and when possible a hash over the sorted file ids so deletions and replacements are seen.
Snapshots come from the Harvey Vault API when it is configured, or are supplied manually;
findings carry the provenance because a manual snapshot is a weaker claim.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from . import harvey
from .db import now
from .findings import Finding, PromptGraphError
from .service import _provenance, get_matter, get_table, table_columns

CACHE_WINDOW_SECONDS = 300  # ten requests a minute per org: never poll twice inside five minutes


def table_vault_project(conn: sqlite3.Connection, table: sqlite3.Row) -> str | None:
    if table["vault_project_id"]:
        return table["vault_project_id"]
    m = conn.execute(
        "SELECT vault_project_id FROM matter WHERE id=?", (table["matter_id"],)
    ).fetchone()
    return m["vault_project_id"] if m else None


def latest_snapshot(
    conn: sqlite3.Connection, matter_id: int, vault_project_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT * FROM document_set_snapshot WHERE matter_id=? AND vault_project_id=?
           ORDER BY observed_at DESC, id DESC LIMIT 1""",
        (matter_id, vault_project_id),
    ).fetchone()


def set_hash(file_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(file_ids)).encode()).hexdigest()[:16]


def record_snapshot(
    conn: sqlite3.Connection,
    matter_id: int,
    vault_project_id: str,
    source: str,
    ready_count: int | None,
    latest_uploaded_at: str | None,
    file_ids: list[str] | None,
    note: str | None = None,
    observed_at: str | None = None,
    actor: str | None = None,
) -> sqlite3.Row:
    if source not in ("harvey_api", "manual"):
        raise PromptGraphError("snapshot source must be harvey_api or manual.")
    if file_ids is not None:
        ready_count = len(file_ids)
    if ready_count is None:
        raise PromptGraphError("A document-set snapshot needs at least a ready document count.")
    cur = conn.execute(
        """INSERT INTO document_set_snapshot (matter_id, vault_project_id, observed_at, ready_count,
               latest_uploaded_at, set_hash, file_ids, source, note, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            matter_id,
            vault_project_id,
            observed_at or now(),
            ready_count,
            latest_uploaded_at,
            set_hash(file_ids) if file_ids is not None else None,
            json.dumps(sorted(file_ids)) if file_ids is not None else None,
            source,
            note,
            now(),
        ),
    )
    _provenance(
        conn,
        "document_set_snapshot",
        cur.lastrowid,
        "observe",
        source,
        actor,
        {"ready_count": ready_count},
    )
    return conn.execute(
        "SELECT * FROM document_set_snapshot WHERE id=?", (cur.lastrowid,)
    ).fetchone()


def diff(prev: sqlite3.Row | None, cur: sqlite3.Row | None) -> dict[str, Any]:
    """What changed between two snapshots of the same project. `moved` is the verdict-free fact."""
    if prev is None or cur is None:
        return {"comparable": False, "moved": None}
    out: dict[str, Any] = {"comparable": True, "moved": False, "basis": "count"}
    if prev["ready_count"] is not None and cur["ready_count"] is not None:
        out["ready_delta"] = int(cur["ready_count"]) - int(prev["ready_count"])
        out["ready_before"] = int(prev["ready_count"])
        out["ready_after"] = int(cur["ready_count"])
        if out["ready_delta"] != 0:
            out["moved"] = True
    if (
        prev["latest_uploaded_at"]
        and cur["latest_uploaded_at"]
        and cur["latest_uploaded_at"] > prev["latest_uploaded_at"]
    ):
        out["latest_upload_moved"] = True
        out["moved"] = True
    if prev["file_ids"] and cur["file_ids"]:
        a, b = set(json.loads(prev["file_ids"])), set(json.loads(cur["file_ids"]))
        out["basis"] = "file_ids"
        out["added"] = len(b - a)
        out["removed"] = len(a - b)
        if a != b:
            out["moved"] = True
    elif prev["set_hash"] and cur["set_hash"] and prev["set_hash"] != cur["set_hash"]:
        out["basis"] = "hash"
        out["moved"] = True
    return out


def _run_snapshot(conn: sqlite3.Connection, run: sqlite3.Row | None) -> sqlite3.Row | None:
    if run is None or run["document_set_snapshot_id"] is None:
        return None
    return conn.execute(
        "SELECT * FROM document_set_snapshot WHERE id=?", (run["document_set_snapshot_id"],)
    ).fetchone()


def freshness_map(conn: sqlite3.Connection, matter_id: int) -> dict[int, dict[str, Any]]:
    """Per table: state ∈ unobserved | never_run | unrecorded | current | moved, with the diff."""
    from .evaluation import latest_run

    out: dict[int, dict[str, Any]] = {}
    for t in conn.execute(
        "SELECT * FROM review_table WHERE matter_id=? ORDER BY position, name", (matter_id,)
    ):
        tid = int(t["id"])
        project = table_vault_project(conn, t)
        current = latest_snapshot(conn, matter_id, project) if project else None
        run = latest_run(conn, tid)
        ran_against = _run_snapshot(conn, run)
        entry: dict[str, Any] = {
            "table": t["name"],
            "vault_project_id": project,
            "current_snapshot": _snap_dict(current),
            "last_run_snapshot": _snap_dict(ran_against),
        }
        if current is None:
            entry["state"] = "unobserved"
        elif run is None:
            entry["state"] = "never_run"
        elif ran_against is None:
            entry["state"] = "unrecorded"
        else:
            d = diff(ran_against, current)
            entry["diff"] = d
            entry["state"] = "moved" if d.get("moved") else "current"
        out[tid] = entry
    return out


def _snap_dict(s: sqlite3.Row | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "snapshot_id": int(s["id"]),
        "observed_at": s["observed_at"],
        "ready_count": s["ready_count"],
        "latest_uploaded_at": s["latest_uploaded_at"],
        "source": s["source"],
        "has_file_ids": bool(s["file_ids"]),
    }


def freshness_findings(
    conn: sqlite3.Connection, matter_id: int, fmap: dict[int, dict[str, Any]] | None = None
) -> list[Finding]:
    fmap = fmap if fmap is not None else freshness_map(conn, matter_id)
    findings: list[Finding] = []
    for tid, e in fmap.items():
        name = e["table"]
        if e["state"] == "moved":
            d = e["diff"]
            cur = e["current_snapshot"]
            if d.get("basis") == "file_ids":
                what = f"{d['added']} added and {d['removed']} removed since"
            elif "ready_delta" in d:
                what = f"the count has moved by {d['ready_delta']:+d} since"
            else:
                what = "the set has changed since"
            findings.append(
                Finding(
                    "DOCSET_MOVED",
                    "table",
                    tid,
                    name,
                    f"Columns in '{name}' last ran against {e['last_run_snapshot']['ready_count']} ready documents; {what} ({cur['source']} observation at {cur['observed_at']}).",
                    {"diff": d, "current": cur, "ran_against": e["last_run_snapshot"]},
                )
            )
        elif e["state"] == "unrecorded":
            findings.append(
                Finding(
                    "DOCSET_UNRECORDED",
                    "table",
                    tid,
                    name,
                    f"The last run of '{name}' has no document-set snapshot, so freshness cannot be compared for it.",
                    {"current": e["current_snapshot"]},
                )
            )
        elif e["state"] == "unobserved" and e["vault_project_id"]:
            findings.append(
                Finding(
                    "DOCSET_UNOBSERVED",
                    "table",
                    tid,
                    name,
                    f"No document-set snapshot exists for '{name}' (vault project {e['vault_project_id']}).",
                    {},
                )
            )
        elif e["state"] == "unobserved":
            findings.append(
                Finding(
                    "DOCSET_NO_PROJECT",
                    "table",
                    tid,
                    name,
                    f"'{name}' has no vault project id, on the table or the matter, so its document set cannot be tracked.",
                    {},
                )
            )
    return findings


def freshness_check(
    conn: sqlite3.Connection,
    matter: str,
    table: str | None = None,
    refresh: bool = False,
    ready_count: int | None = None,
    as_of: str | None = None,
    latest_uploaded_at: str | None = None,
    file_ids: list[str] | None = None,
    vault_project_id: str | None = None,
    note: str | None = None,
    force: bool = False,
    actor: str | None = None,
    fetcher: harvey.Fetcher | None = None,
) -> dict[str, Any]:
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    refreshed: list[dict[str, Any]] = []
    findings: list[Finding] = []

    if refresh:
        # Which projects to observe: the named table's, or every distinct project in the matter.
        projects: list[str] = []
        if vault_project_id:
            projects = [vault_project_id]
        elif table:
            t = get_table(conn, matter_id, table)
            p = table_vault_project(conn, t)
            if not p:
                raise PromptGraphError(
                    f"Table '{t['name']}' has no vault project id; set one on the table or the matter, or pass vault_project_id."
                )
            projects = [p]
        else:
            seen: dict[str, None] = {}
            for t in conn.execute("SELECT * FROM review_table WHERE matter_id=?", (matter_id,)):
                p = table_vault_project(conn, t)
                if p:
                    seen[p] = None
            if not seen and m["vault_project_id"]:
                seen[m["vault_project_id"]] = None
            projects = list(seen)
            if not projects:
                raise PromptGraphError(
                    "No vault project id is set on the matter or any table; pass vault_project_id."
                )
        manual = ready_count is not None or file_ids is not None
        if manual and len(projects) > 1:
            raise PromptGraphError(
                "A manual count applies to one vault project; name the table or pass vault_project_id."
            )
        # Vault's ten-a-minute limit is per organisation, so the budget is shared across every
        # project observed in this call, not spent afresh on each one.
        budget = harvey.MAX_REQUESTS_PER_POLL
        for p in projects:
            prev = latest_snapshot(conn, matter_id, p)
            if manual:
                conn.execute("BEGIN")
                try:
                    snap = record_snapshot(
                        conn,
                        matter_id,
                        p,
                        "manual",
                        ready_count,
                        latest_uploaded_at,
                        file_ids,
                        note,
                        as_of,
                        actor,
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                refreshed.append(
                    {
                        "vault_project_id": p,
                        "source": "manual",
                        "snapshot": _snap_dict(snap),
                        "change_since_previous": diff(prev, snap),
                    }
                )
                continue
            # API path, rate-limit aware.
            if prev is not None and prev["source"] == "harvey_api" and not force:
                age = (
                    datetime.now(UTC) - datetime.fromisoformat(prev["observed_at"])
                ).total_seconds()
                if age < CACHE_WINDOW_SECONDS:
                    refreshed.append(
                        {
                            "vault_project_id": p,
                            "source": "cache",
                            "snapshot": _snap_dict(prev),
                            "age_seconds": int(age),
                            "change_since_previous": None,
                        }
                    )
                    continue
            if budget < 1:
                findings.append(
                    Finding(
                        "DOCSET_POLL_BUDGET_SPENT",
                        "matter",
                        matter_id,
                        m["name"],
                        f"Vault project {p} was not observed because this call's Vault request "
                        f"budget was already spent on earlier projects.",
                        {"vault_project_id": p, "request_budget": harvey.MAX_REQUESTS_PER_POLL},
                    )
                )
                continue
            try:
                files, requests, complete = harvey.list_ready_files(
                    p, fetcher=fetcher, max_requests=budget
                )
            except harvey.HarveyUnavailable as e:
                if e.rate_limited:
                    # The limit is organisation-wide, so polling the next project would only
                    # produce the same 429. Stop, and report the ones left unobserved.
                    budget = 0
                findings.append(
                    Finding(
                        "HARVEY_UNAVAILABLE",
                        "matter",
                        matter_id,
                        m["name"],
                        f"The Harvey Vault API could not be used for project {p}: {e}",
                        {"vault_project_id": p},
                    )
                )
                continue
            budget -= requests
            if not complete:
                # A prefix of the file list is not the document set. Recording it would put a
                # false count into the snapshot history and read later as documents removed.
                findings.append(
                    Finding(
                        "DOCSET_TOO_LARGE_TO_ENUMERATE",
                        "matter",
                        matter_id,
                        m["name"],
                        f"Vault project {p} holds more ready documents than {harvey.MAX_REQUESTS_PER_POLL} "
                        f"requests of {harvey.PAGE_SIZE} can enumerate, so no snapshot was recorded; "
                        f"{len(files)} documents were seen before the budget ran out.",
                        {
                            "vault_project_id": p,
                            "documents_seen": len(files),
                            "requests_spent": requests,
                            "request_budget": harvey.MAX_REQUESTS_PER_POLL,
                        },
                    )
                )
                continue
            latest = max((f["uploaded_at"] for f in files if f.get("uploaded_at")), default=None)
            conn.execute("BEGIN")
            try:
                snap = record_snapshot(
                    conn,
                    matter_id,
                    p,
                    "harvey_api",
                    len(files),
                    latest,
                    [f["id"] for f in files],
                    note,
                    None,
                    actor,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            refreshed.append(
                {
                    "vault_project_id": p,
                    "source": "harvey_api",
                    "requests_used": requests,
                    "snapshot": _snap_dict(snap),
                    "change_since_previous": diff(prev, snap),
                }
            )

    fmap = freshness_map(conn, matter_id)
    if table:
        t = get_table(conn, matter_id, table)
        fmap = {int(t["id"]): fmap[int(t["id"])]}
    findings.extend(freshness_findings(conn, matter_id, fmap))
    counts: dict[str, int] = {}
    for e in fmap.values():
        counts[e["state"]] = counts.get(e["state"], 0) + 1
    # Memo consequences (A.2): assertions whose sources ran against a moved set.
    from .coverage import assertions_for_columns

    affected: dict[int, str] = {}
    for tid, e in fmap.items():
        if e["state"] == "moved":
            for c in table_columns(conn, tid):
                affected[int(c["id"])] = "document set moved since last run"
    memo = assertions_for_columns(conn, matter_id, affected) if affected else []
    return {
        "matter": m["name"],
        "harvey_api_configured": harvey.configured(),
        "refreshed": refreshed,
        "counts": counts,
        "tables": list(fmap.values()),
        "memo_consequences": memo,
        "findings": findings,
    }
