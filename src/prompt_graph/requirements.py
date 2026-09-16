"""The requirement register: the external specification a suite is built to satisfy.

Coverage asks whether the memo this team wrote can be supported by the columns this team wrote.
A requirement source is the independent standard. Recording it means a playbook prompt that maps
to *no* review table becomes a stored finding with a reason, rather than an absence.

Disposition lives on a part, not on a requirement, because a real set splits: "Part A needs the
buyer's checklist, Part B becomes memo section IV.B" is one requirement with two answers.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import now
from .findings import Finding, PromptGraphError
from .service import _norm, _provenance, get_matter, get_table

DISPOSITIONS = ("served", "synthesis", "external", "unassessed")
LINK_KINDS = ("served_by", "consumes", "produces")


def _source(conn: sqlite3.Connection, matter_id: int, name: str | None) -> sqlite3.Row:
    if name:
        row = conn.execute(
            "SELECT * FROM requirement_source WHERE matter_id=? AND name=? COLLATE NOCASE",
            (matter_id, _norm(name)),
        ).fetchone()
        if row is None:
            known = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM requirement_source WHERE matter_id=?", (matter_id,)
                )
            ]
            raise PromptGraphError(
                f"No requirement source named '{name}'. Known: {', '.join(known) or 'none yet'}."
            )
        return row
    rows = conn.execute(
        "SELECT * FROM requirement_source WHERE matter_id=? ORDER BY id", (matter_id,)
    ).fetchall()
    if not rows:
        raise PromptGraphError(
            "No requirement source is stored for this matter. Use requirements_ingest first."
        )
    if len(rows) > 1:
        raise PromptGraphError(
            "This matter has more than one requirement source; name the one you mean: "
            + ", ".join(r["name"] for r in rows)
        )
    return rows[0]


def _section_id(conn: sqlite3.Connection, matter_id: int, name: str) -> int | None:
    row = conn.execute(
        """SELECT ms.id FROM memo_section ms JOIN memo_outline mo ON mo.id = ms.outline_id
           WHERE mo.matter_id = ? AND mo.is_current = 1 AND ms.name = ? COLLATE NOCASE""",
        (matter_id, _norm(name)),
    ).fetchone()
    return int(row["id"]) if row else None


def _write_parts(
    conn: sqlite3.Connection,
    matter_id: int,
    req_id: int,
    parts: list[dict[str, Any]],
    findings: list[Finding],
    ref: str,
) -> None:
    """Replace a requirement's parts. Parts and their links are one unit: a disposition without
    its links is meaningless, so a partial update would leave the register lying."""
    conn.execute(
        "DELETE FROM requirement_link WHERE part_id IN"
        " (SELECT id FROM requirement_part WHERE requirement_id=?)",
        (req_id,),
    )
    conn.execute("DELETE FROM requirement_part WHERE requirement_id=?", (req_id,))
    for i, p in enumerate(parts or [{"disposition": "unassessed"}], start=1):
        disp = (p.get("disposition") or "unassessed").strip().lower()
        if disp not in DISPOSITIONS:
            findings.append(
                Finding(
                    "REQUIREMENT_DISPOSITION_INVALID",
                    "matter",
                    matter_id,
                    ref,
                    f"'{disp}' is not a disposition; recorded as unassessed. "
                    f"One of: {', '.join(DISPOSITIONS)}.",
                    {"ref": ref, "submitted": disp},
                )
            )
            disp = "unassessed"
        cur = conn.execute(
            "INSERT INTO requirement_part (requirement_id, label, position, disposition, reason)"
            " VALUES (?, ?, ?, ?, ?)",
            (req_id, (p.get("label") or "").strip() or None, i, disp, p.get("reason")),
        )
        part_id = int(cur.lastrowid)
        for link in p.get("links") or []:
            kind = (link.get("kind") or "").strip().lower()
            if kind not in LINK_KINDS:
                findings.append(
                    Finding(
                        "REQUIREMENT_LINK_INVALID",
                        "matter",
                        matter_id,
                        ref,
                        f"'{kind}' is not a link kind; the link was dropped. "
                        f"One of: {', '.join(LINK_KINDS)}.",
                        {"ref": ref, "submitted": kind},
                    )
                )
                continue
            table_id = section_id = None
            if kind == "produces":
                section_id = _section_id(conn, matter_id, link.get("section") or "")
                if section_id is None:
                    findings.append(
                        Finding(
                            "REQUIREMENT_SECTION_MISSING",
                            "matter",
                            matter_id,
                            ref,
                            f"{ref} produces memo section '{link.get('section')}', which the "
                            f"current outline does not contain.",
                            {"ref": ref, "section": link.get("section")},
                        )
                    )
                    continue
            else:
                try:
                    table_id = int(get_table(conn, matter_id, link.get("table") or "")["id"])
                except PromptGraphError:
                    findings.append(
                        Finding(
                            "REQUIREMENT_TABLE_MISSING",
                            "matter",
                            matter_id,
                            ref,
                            f"{ref} names table '{link.get('table')}', which this matter does "
                            f"not have.",
                            {"ref": ref, "table": link.get("table")},
                        )
                    )
                    continue
            conn.execute(
                "INSERT OR IGNORE INTO requirement_link (part_id, kind, table_id, section_id, note)"
                " VALUES (?, ?, ?, ?, ?)",
                (part_id, kind, table_id, section_id, link.get("note")),
            )


def requirements_ingest(
    conn: sqlite3.Connection,
    matter: str,
    source: str,
    items: list[dict[str, Any]],
    citation: str | None = None,
    version: str | None = None,
    note: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Store a requirement source and its items. Re-ingesting is safe: items match on `ref`."""
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    findings: list[Finding] = []
    name = _norm(source)

    row = conn.execute(
        "SELECT * FROM requirement_source WHERE matter_id=? AND name=? COLLATE NOCASE",
        (matter_id, name),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO requirement_source (matter_id, name, citation, version, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (matter_id, name, citation, version, note, now()),
        )
        source_id = int(cur.lastrowid)
        _provenance(conn, "requirement_source", source_id, "create", "chat", actor, {"name": name})
    else:
        source_id = int(row["id"])
        if citation or version or note:
            conn.execute(
                "UPDATE requirement_source SET citation=COALESCE(?, citation),"
                " version=COALESCE(?, version), note=COALESCE(?, note) WHERE id=?",
                (citation, version, note, source_id),
            )

    created, updated = [], []
    for i, it in enumerate(items, start=1):
        ref = _norm(str(it.get("ref") or ""))
        if not ref:
            findings.append(
                Finding(
                    "REQUIREMENT_REF_MISSING",
                    "matter",
                    matter_id,
                    m["name"],
                    "A submitted item has no reference and was skipped.",
                    {"title": it.get("title")},
                )
            )
            continue
        existing = conn.execute(
            "SELECT id FROM requirement WHERE source_id=? AND ref=?", (source_id, ref)
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                "INSERT INTO requirement (source_id, ref, position, title, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    source_id,
                    ref,
                    it.get("position") or i,
                    _norm(it.get("title") or ref),
                    it.get("note"),
                    now(),
                ),
            )
            req_id = int(cur.lastrowid)
            created.append(ref)
        else:
            req_id = int(existing["id"])
            conn.execute(
                "UPDATE requirement SET title=COALESCE(?, title), note=COALESCE(?, note),"
                " position=COALESCE(?, position) WHERE id=?",
                (it.get("title"), it.get("note"), it.get("position"), req_id),
            )
            updated.append(ref)
        _write_parts(conn, matter_id, req_id, it.get("parts") or [], findings, ref)

    return {
        "matter": m["name"],
        "source": name,
        "created": sorted(created),
        "updated": sorted(updated),
        "count": len(created) + len(updated),
        "findings": findings,
    }


def requirement_set(
    conn: sqlite3.Connection,
    matter: str,
    ref: str,
    parts: list[dict[str, Any]],
    source: str | None = None,
    title: str | None = None,
    note: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Replace one requirement's disposition and links. Parts are replaced wholesale."""
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    src = _source(conn, matter_id, source)
    row = conn.execute(
        "SELECT * FROM requirement WHERE source_id=? AND ref=?", (int(src["id"]), _norm(ref))
    ).fetchone()
    if row is None:
        raise PromptGraphError(f"No requirement '{ref}' in source '{src['name']}'.")
    if title or note:
        conn.execute(
            "UPDATE requirement SET title=COALESCE(?, title), note=COALESCE(?, note) WHERE id=?",
            (title, note, int(row["id"])),
        )
    findings: list[Finding] = []
    _write_parts(conn, matter_id, int(row["id"]), parts, findings, row["ref"])
    _provenance(
        conn,
        "requirement",
        int(row["id"]),
        "disposition",
        "chat",
        actor,
        {"ref": row["ref"], "parts": [p.get("disposition") for p in parts]},
    )
    return {
        "matter": m["name"],
        "source": src["name"],
        "ref": row["ref"],
        "parts": len(parts),
        "findings": findings,
    }


def register(conn: sqlite3.Connection, matter: str) -> dict[str, Any]:
    """The register, and the two directions over it: what each requirement resolved to, and
    which tables answer no requirement at all."""
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    sources = conn.execute(
        "SELECT * FROM requirement_source WHERE matter_id=? ORDER BY id", (matter_id,)
    ).fetchall()
    out_sources = []
    served_tables: set[int] = set()
    counts = dict.fromkeys(DISPOSITIONS, 0)

    for src in sources:
        reqs = []
        for r in conn.execute(
            "SELECT * FROM requirement WHERE source_id=? ORDER BY position, ref", (int(src["id"]),)
        ):
            parts = []
            for p in conn.execute(
                "SELECT * FROM requirement_part WHERE requirement_id=? ORDER BY position",
                (int(r["id"]),),
            ):
                links = [
                    {
                        "kind": link["kind"],
                        "table": link["table_name"],
                        "section": link["section_name"],
                        "note": link["note"],
                    }
                    for link in conn.execute(
                        """SELECT rl.kind, rl.note, rt.name AS table_name, ms.name AS section_name,
                                  rl.table_id
                           FROM requirement_link rl
                           LEFT JOIN review_table rt ON rt.id = rl.table_id
                           LEFT JOIN memo_section ms ON ms.id = rl.section_id
                           WHERE rl.part_id = ?""",
                        (int(p["id"]),),
                    )
                ]
                for link in conn.execute(
                    "SELECT table_id FROM requirement_link WHERE part_id=? AND table_id IS NOT NULL",
                    (int(p["id"]),),
                ):
                    served_tables.add(int(link["table_id"]))
                counts[p["disposition"]] = counts.get(p["disposition"], 0) + 1
                parts.append(
                    {
                        "label": p["label"],
                        "disposition": p["disposition"],
                        "reason": p["reason"],
                        "links": links,
                    }
                )
            reqs.append({"ref": r["ref"], "title": r["title"], "note": r["note"], "parts": parts})
        out_sources.append(
            {
                "source": src["name"],
                "citation": src["citation"],
                "version": src["version"],
                "note": src["note"],
                "requirements": reqs,
            }
        )

    unserved = [
        {"table": t["name"], "position": t["position"]}
        for t in conn.execute(
            "SELECT id, name, position FROM review_table WHERE matter_id=? ORDER BY position, name",
            (matter_id,),
        )
        if int(t["id"]) not in served_tables
    ]
    total = sum(len(r["requirements"]) for r in out_sources)
    return {
        "matter": m["name"],
        "sources": out_sources,
        "counts": {**counts, "requirements": total},
        "tables_answering_nothing": unserved,
        "findings": [],
    }
