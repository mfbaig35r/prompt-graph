"""Matter, standard, ingest, revision, and read operations.

Everything here is name-addressed: matters, tables, columns, and parameters are looked up by
the name the user uses. Internal ids are returned for Claude's convenience, never required.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import lint
from .constants import (
    COLUMN_ROLES,
    COLUMN_STATUSES,
    FALLBACK_VOCABULARY,
    NATIVE_TYPE_ALIASES,
    NATIVE_TYPES,
)
from .db import now
from .findings import Finding, PromptGraphError
from .models import ColumnRecord, EntityRecord, TableMeta, fold
from .refs import referenced_names

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def _norm(name: str) -> str:
    return " ".join(name.split()).strip()


def get_matter(conn: sqlite3.Connection, matter: str | int) -> sqlite3.Row:
    if isinstance(matter, int) or (isinstance(matter, str) and matter.isdigit()):
        row = conn.execute("SELECT * FROM matter WHERE id=?", (int(matter),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM matter WHERE name=?", (_norm(matter),)).fetchone()
    if row is None:
        names = [r["name"] for r in conn.execute("SELECT name FROM matter ORDER BY name")]
        raise PromptGraphError(
            f"No matter named '{matter}'. Known matters: {', '.join(names) or 'none yet'}. "
            "Use matter_open with create=true to start one."
        )
    return row


def get_table(conn: sqlite3.Connection, matter_id: int, table: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM review_table WHERE matter_id=? AND name=?", (matter_id, _norm(table))
    ).fetchone()
    if row is None:
        names = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM review_table WHERE matter_id=? ORDER BY position, name",
                (matter_id,),
            )
        ]
        raise PromptGraphError(
            f"No table named '{table}' in this matter. Tables: {', '.join(names) or 'none yet'}."
        )
    return row


def get_column(conn: sqlite3.Connection, table_id: int, column: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM column_def WHERE table_id=? AND name=?", (table_id, _norm(column))
    ).fetchone()
    if row is None:
        names = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM column_def WHERE table_id=? ORDER BY position", (table_id,)
            )
        ]
        raise PromptGraphError(
            f"No column named '{column}' in this table. Columns: {', '.join(names) or 'none'}."
        )
    return row


def get_parameter(conn: sqlite3.Connection, matter_id: int, name: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM shared_parameter WHERE matter_id=? AND name=?", (matter_id, _norm(name))
    ).fetchone()
    if row is None:
        names = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM shared_parameter WHERE matter_id=? ORDER BY name", (matter_id,)
            )
        ]
        raise PromptGraphError(
            f"No shared parameter named '{name}'. Parameters: {', '.join(names) or 'none yet'}."
        )
    return row


def table_columns(
    conn: sqlite3.Connection, table_id: int, include_retired: bool = False
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM column_def WHERE table_id=?"
    if not include_retired:
        sql += " AND status != 'retired'"
    return conn.execute(sql + " ORDER BY position, id", (table_id,)).fetchall()


def current_prompt(conn: sqlite3.Connection, column_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM prompt_version WHERE column_id=? AND is_current=1", (column_id,)
    ).fetchone()


def current_instructions(conn: sqlite3.Connection, table_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM table_instructions WHERE table_id=? AND is_current=1", (table_id,)
    ).fetchone()


def _provenance(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int | None,
    action: str,
    source_type: str | None = None,
    actor: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO provenance (entity_type, entity_id, action, source_type, actor, at, detail)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entity_type, entity_id, action, source_type, actor, now(), json.dumps(detail or {})),
    )


def _options(row: sqlite3.Row) -> list[str] | None:
    raw = row["configured_options"]
    return json.loads(raw) if raw else None


# ---------------------------------------------------------------------------
# Standard
# ---------------------------------------------------------------------------

_CONSTRAINED_FIELDS = (
    "fallback_vocabulary",
    "date_pattern",
    "currency_pattern",
    "default_evidence_boundary",
)
_ADDITIVE_FIELDS = ("naming_rules", "entities", "objective", "conventions")


def _standard_row(
    conn: sqlite3.Connection, scope: str, matter_id: int | None
) -> sqlite3.Row | None:
    if scope == "firm":
        return conn.execute("SELECT * FROM standard WHERE scope='firm' AND is_current=1").fetchone()
    return conn.execute(
        "SELECT * FROM standard WHERE scope='matter' AND matter_id=? AND is_current=1",
        (matter_id,),
    ).fetchone()


def _standard_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    d["fallback_vocabulary"] = json.loads(d["fallback_vocabulary"] or "[]")
    d["entities"] = json.loads(d["entities"] or "[]")
    d["conventions"] = json.loads(d["conventions"] or "[]")
    return d


def effective_standard(conn: sqlite3.Connection, matter_id: int | None) -> dict[str, Any]:
    """Firm baseline with the matter overlay applied where it does not contradict."""
    firm = _standard_dict(_standard_row(conn, "firm", None))
    overlay = _standard_dict(_standard_row(conn, "matter", matter_id)) if matter_id else {}
    eff: dict[str, Any] = {
        "fallback_vocabulary": firm.get("fallback_vocabulary") or list(FALLBACK_VOCABULARY),
        "date_pattern": firm.get("date_pattern"),
        "currency_pattern": firm.get("currency_pattern"),
        "default_evidence_boundary": firm.get("default_evidence_boundary"),
        "naming_rules": firm.get("naming_rules"),
        "entities": [],
        "objective": None,
        "conventions": list(firm.get("conventions") or []),
        "firm_version": firm.get("version"),
        "matter_version": overlay.get("version"),
        "overridden_by_firm": [],
    }
    if overlay:
        for f in _CONSTRAINED_FIELDS:
            ov = overlay.get(f)
            if ov in (None, "", []):
                continue
            base = eff[f]
            if base in (None, "", []):
                eff[f] = ov
            elif ov != base:
                eff["overridden_by_firm"].append(f)
        if overlay.get("naming_rules"):
            eff["naming_rules"] = overlay["naming_rules"]
        eff["entities"] = overlay.get("entities") or []
        eff["objective"] = overlay.get("objective")
        eff["conventions"] = eff["conventions"] + list(overlay.get("conventions") or [])
    return eff


def standard_set(
    conn: sqlite3.Connection,
    scope: str,
    matter: str | None = None,
    fallback_vocabulary: list[str] | None = None,
    naming_rules: str | None = None,
    date_pattern: str | None = None,
    currency_pattern: str | None = None,
    default_evidence_boundary: str | None = None,
    entities: list[EntityRecord] | None = None,
    objective: str | None = None,
    conventions: list[str] | None = None,
    change_note: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    scope = fold(scope)
    if scope not in ("firm", "matter"):
        raise PromptGraphError("scope must be 'firm' or 'matter'.")
    matter_id: int | None = None
    if scope == "matter":
        if not matter:
            raise PromptGraphError("A matter name is required for a matter standard.")
        matter_id = int(get_matter(conn, matter)["id"])
    prev = _standard_dict(_standard_row(conn, scope, matter_id))
    findings: list[Finding] = []

    # Fields not supplied carry forward from the previous version of the same scope.
    new = {
        "fallback_vocabulary": fallback_vocabulary
        if fallback_vocabulary is not None
        else prev.get("fallback_vocabulary", list(FALLBACK_VOCABULARY) if scope == "firm" else []),
        "naming_rules": naming_rules if naming_rules is not None else prev.get("naming_rules"),
        "date_pattern": date_pattern if date_pattern is not None else prev.get("date_pattern"),
        "currency_pattern": currency_pattern
        if currency_pattern is not None
        else prev.get("currency_pattern"),
        "default_evidence_boundary": default_evidence_boundary
        if default_evidence_boundary is not None
        else prev.get("default_evidence_boundary"),
        "entities": [e.model_dump() for e in entities]
        if entities is not None
        else prev.get("entities", []),
        "objective": objective if objective is not None else prev.get("objective"),
        "conventions": conventions if conventions is not None else prev.get("conventions", []),
    }

    subject = "firm baseline" if scope == "firm" else f"matter standard ({matter})"
    if scope == "firm" and list(new["fallback_vocabulary"]) != list(FALLBACK_VOCABULARY):
        findings.append(
            Finding(
                "STANDARD_VOCABULARY_NOT_SKILL",
                "standard",
                None,
                subject,
                "The firm fallback vocabulary differs from the five states the legal-review-table-builder skill defines.",
                {"submitted": new["fallback_vocabulary"], "skill": list(FALLBACK_VOCABULARY)},
            )
        )
    if scope == "matter":
        firm = _standard_dict(_standard_row(conn, "firm", None))
        for f in _CONSTRAINED_FIELDS:
            ov = new.get(f)
            base = firm.get(f)
            if ov in (None, "", []) or base in (None, "", []):
                continue
            if ov != base:
                findings.append(
                    Finding(
                        "STANDARD_CONTRADICTS_FIRM",
                        "standard",
                        None,
                        subject,
                        f"The matter overlay sets {f} to a value different from the firm baseline; the firm value remains effective.",
                        {"field": f, "matter_value": ov, "firm_value": base},
                    )
                )

    version = int(prev.get("version") or 0) + 1
    conn.execute("BEGIN")
    try:
        if scope == "firm":
            conn.execute("UPDATE standard SET is_current=0 WHERE scope='firm'")
        else:
            conn.execute(
                "UPDATE standard SET is_current=0 WHERE scope='matter' AND matter_id=?",
                (matter_id,),
            )
        cur = conn.execute(
            """INSERT INTO standard (scope, matter_id, version, fallback_vocabulary, naming_rules,
                   date_pattern, currency_pattern, default_evidence_boundary, entities, objective,
                   conventions, change_note, created_at, is_current)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (
                scope,
                matter_id,
                version,
                json.dumps(list(new["fallback_vocabulary"])),
                new["naming_rules"],
                new["date_pattern"],
                new["currency_pattern"],
                new["default_evidence_boundary"],
                json.dumps(new["entities"]),
                new["objective"],
                json.dumps(list(new["conventions"])),
                change_note,
                now(),
            ),
        )
        _provenance(
            conn,
            "standard",
            cur.lastrowid,
            "set",
            "chat",
            actor,
            {"scope": scope, "version": version},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {
        "scope": scope,
        "matter": matter,
        "version": version,
        "effective": effective_standard(conn, matter_id),
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Matter
# ---------------------------------------------------------------------------


def matter_open(
    conn: sqlite3.Connection,
    name: str,
    create: bool = False,
    objective: str | None = None,
    side: str | None = None,
    actor: str | None = None,
    vault_project_id: str | None = None,
) -> tuple[sqlite3.Row, bool]:
    """Return (matter row, created?)."""
    name = _norm(name)
    side = fold(side)
    row = conn.execute("SELECT * FROM matter WHERE name=?", (name,)).fetchone()
    if row is not None:
        if objective is not None or side is not None or vault_project_id is not None:
            conn.execute(
                "UPDATE matter SET objective=COALESCE(?, objective), side=COALESCE(?, side), vault_project_id=COALESCE(?, vault_project_id) WHERE id=?",
                (objective, side, vault_project_id, row["id"]),
            )
            row = conn.execute("SELECT * FROM matter WHERE id=?", (row["id"],)).fetchone()
        return row, False
    if not create:
        return get_matter(conn, name), False  # raises with the list of known matters
    if side is not None and side not in ("buy", "sell"):
        raise PromptGraphError("side must be 'buy' or 'sell'.")
    cur = conn.execute(
        "INSERT INTO matter (name, objective, side, status, created_at, vault_project_id) VALUES (?,?,?,?,?,?)",
        (name, objective, side, "active", now(), vault_project_id),
    )
    _provenance(conn, "matter", cur.lastrowid, "create", "chat", actor, {"name": name})
    return conn.execute("SELECT * FROM matter WHERE id=?", (cur.lastrowid,)).fetchone(), True


def list_matters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM matter ORDER BY name")]


# ---------------------------------------------------------------------------
# Prompt versions and dependencies
# ---------------------------------------------------------------------------


def _new_prompt_version(
    conn: sqlite3.Connection,
    column_id: int,
    text: str,
    change_note: str | None,
    failure_class: str | None,
    bump: str = "minor",
) -> sqlite3.Row:
    cur = current_prompt(conn, column_id)
    if cur is None:
        major, minor = 1, 0
    elif bump == "major":
        major, minor = int(cur["major"]) + 1, 0
    else:
        major, minor = int(cur["major"]), int(cur["minor"]) + 1
    conn.execute("UPDATE prompt_version SET is_current=0 WHERE column_id=?", (column_id,))
    ins = conn.execute(
        """INSERT INTO prompt_version (column_id, version, major, minor, text, char_count,
               change_note, failure_class_addressed, created_at, is_current)
           VALUES (?,?,?,?,?,?,?,?,?,1)""",
        (
            column_id,
            f"v{major}.{minor}",
            major,
            minor,
            text,
            len(text),
            change_note,
            failure_class,
            now(),
        ),
    )
    return conn.execute("SELECT * FROM prompt_version WHERE id=?", (ins.lastrowid,)).fetchone()


def rebuild_intra_refs(
    conn: sqlite3.Connection, table_id: int, column_id: int, declared: list[str] | None = None
) -> tuple[list[str], list[str]]:
    """Recompute intra_table_ref edges into `column_id` from its current prompt text.

    Returns (resolved upstream names, unresolved reference tokens).
    """
    cols = table_columns(conn, table_id, include_retired=True)
    names = [c["name"] for c in cols]
    id_by_name = {c["name"].lower(): int(c["id"]) for c in cols}
    pv = current_prompt(conn, column_id)
    text = pv["text"] if pv else ""
    resolved, unresolved = referenced_names(text, names)
    for d in declared or []:
        d = d.lstrip("@").strip()
        if d.lower() in id_by_name:
            canonical = next(n for n in names if n.lower() == d.lower())
            if canonical not in resolved:
                resolved.append(canonical)
        elif d not in unresolved:
            unresolved.append(d)
    self_name = next(c["name"] for c in cols if int(c["id"]) == column_id)
    resolved = [r for r in resolved if r.lower() != self_name.lower()]
    conn.execute(
        "DELETE FROM dependency WHERE to_column_id=? AND kind='intra_table_ref'", (column_id,)
    )
    for r in resolved:
        conn.execute(
            """INSERT OR IGNORE INTO dependency (from_column_id, to_column_id, kind, declared_by)
               VALUES (?, ?, 'intra_table_ref', 'ingest')""",
            (id_by_name[r.lower()], column_id),
        )
    return resolved, unresolved


def _set_advisory(
    conn: sqlite3.Connection,
    matter_id: int,
    column_id: int,
    column_name: str,
    advisory: list[Any],
) -> list[Finding]:
    findings: list[Finding] = []
    conn.execute("DELETE FROM dependency WHERE to_column_id=? AND kind='advisory'", (column_id,))
    for ref in advisory:
        try:
            t = get_table(conn, matter_id, ref.table)
            c = get_column(conn, int(t["id"]), ref.column)
        except PromptGraphError as e:
            findings.append(
                Finding(
                    "ADVISORY_REF_UNRESOLVED",
                    "column",
                    column_id,
                    column_name,
                    f"The advisory dependency on '{ref.table}' / '{ref.column}' does not match a stored column.",
                    {"table": ref.table, "column": ref.column, "detail": str(e)},
                )
            )
            continue
        conn.execute(
            """INSERT OR IGNORE INTO dependency (from_column_id, to_column_id, kind, declared_by, note)
               VALUES (?, ?, 'advisory', 'user', ?)""",
            (int(c["id"]), column_id, ref.note),
        )
    return findings


def lint_column(conn: sqlite3.Connection, column: sqlite3.Row) -> list[Finding]:
    pv = current_prompt(conn, int(column["id"]))
    if pv is None:
        return []
    cols = table_columns(conn, int(column["table_id"]), include_retired=True)
    ctx = lint.PromptContext(
        native_type=column["native_type"],
        configured_options=_options(column),
        column_name=column["name"],
        column_position=int(column["position"]),
        table_columns=[(c["name"], int(c["position"])) for c in cols],
    )
    out = lint.check_prompt(pv["text"], ctx, subject_name=column["name"])
    for f in out:
        f.subject_id = int(column["id"])
        f.subject_type = "column"
    return out


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def _validate_record(rec: ColumnRecord, table_name: str) -> list[Finding]:
    findings: list[Finding] = []
    subj = rec.name
    if rec.native_type is None:
        findings.append(
            Finding(
                "NATIVE_TYPE_MISSING",
                "column",
                None,
                subj,
                "The record has no native column type.",
                {"table": table_name, "accepted": list(NATIVE_TYPES)},
            )
        )
    elif rec.native_type not in NATIVE_TYPES:
        findings.append(
            Finding(
                "NATIVE_TYPE_INVALID",
                "column",
                None,
                subj,
                f"The native type '{rec.native_type}' is not one of Harvey's column types.",
                {
                    "table": table_name,
                    "accepted": list(NATIVE_TYPES),
                    "aliases": sorted(NATIVE_TYPE_ALIASES),
                },
            )
        )
    if rec.native_type == "Classify":
        if not rec.configured_options:
            findings.append(
                Finding(
                    "OPTIONS_MISSING",
                    "column",
                    None,
                    subj,
                    "This Classify column has no configured option set.",
                    {"table": table_name},
                )
            )
        else:
            cleaned = [o.strip() for o in rec.configured_options]
            if any(not o for o in cleaned) or len(set(o.lower() for o in cleaned)) != len(cleaned):
                findings.append(
                    Finding(
                        "OPTIONS_MALFORMED",
                        "column",
                        None,
                        subj,
                        "The configured option set contains an empty or duplicate option.",
                        {"table": table_name, "options": rec.configured_options},
                    )
                )
    elif rec.configured_options:
        findings.append(
            Finding(
                "OPTIONS_ON_NON_CLASSIFY",
                "column",
                None,
                subj,
                f"Configured options are recorded on a {rec.native_type} column, which does not use them.",
                {"table": table_name, "options": rec.configured_options},
            )
        )
    if rec.status is not None and rec.status not in COLUMN_STATUSES:
        findings.append(
            Finding(
                "STATUS_INVALID",
                "column",
                None,
                subj,
                f"The status '{rec.status}' is not one of {', '.join(COLUMN_STATUSES)}.",
                {"table": table_name},
            )
        )
    if rec.role is not None and rec.role not in COLUMN_ROLES:
        findings.append(
            Finding(
                "ROLE_INVALID",
                "column",
                None,
                subj,
                f"The role '{rec.role}' is not one of {', '.join(COLUMN_ROLES)}.",
                {"table": table_name},
            )
        )
    return findings


def table_ingest(
    conn: sqlite3.Connection,
    matter: str,
    table: str,
    columns: list[ColumnRecord],
    table_meta: TableMeta | None = None,
    table_instructions: str | None = None,
    source_type: str = "chat",
    actor: str | None = None,
    change_note: str | None = None,
) -> dict[str, Any]:
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    table = _norm(table)
    findings: list[Finding] = []

    # Shape validation first; a record with a fatal defect is skipped, not stored.
    fatal_codes = {"NATIVE_TYPE_MISSING", "NATIVE_TYPE_INVALID", "STATUS_INVALID", "ROLE_INVALID"}
    accepted: list[ColumnRecord] = []
    seen_names: set[str] = set()
    seen_pos: dict[int, str] = {}
    for rec in columns:
        rec.name = _norm(rec.name)
        recf = _validate_record(rec, table)
        if rec.name.lower() in seen_names:
            recf.append(
                Finding(
                    "COLUMN_NAME_DUPLICATE",
                    "column",
                    None,
                    rec.name,
                    "The same column name appears more than once in the submitted records.",
                    {"table": table},
                )
            )
            fatal = True
        else:
            fatal = any(f.code in fatal_codes for f in recf)
        if rec.position in seen_pos and rec.name.lower() not in seen_names:
            recf.append(
                Finding(
                    "POSITION_DUPLICATE",
                    "column",
                    None,
                    rec.name,
                    f"Position {rec.position} is also used by '{seen_pos[rec.position]}'.",
                    {"table": table, "position": rec.position},
                )
            )
        seen_names.add(rec.name.lower())
        seen_pos.setdefault(rec.position, rec.name)
        findings.extend(recf)
        if not fatal:
            accepted.append(rec)

    created: list[str] = []
    new_versions: list[dict[str, Any]] = []
    unchanged: list[str] = []
    meta = table_meta or TableMeta()

    conn.execute("BEGIN")
    try:
        trow = conn.execute(
            "SELECT * FROM review_table WHERE matter_id=? AND name=?", (matter_id, table)
        ).fetchone()
        if trow is None:
            pos = meta.position
            if pos is None:
                pos = conn.execute(
                    "SELECT COALESCE(MAX(position),0)+1 FROM review_table WHERE matter_id=?",
                    (matter_id,),
                ).fetchone()[0]
            cur = conn.execute(
                """INSERT INTO review_table (matter_id, name, review_unit, platform, grouping_enabled,
                       max_docs_per_unit, stage, position, created_at, vault_project_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    matter_id,
                    table,
                    meta.review_unit,
                    meta.platform,
                    int(meta.grouping_enabled),
                    meta.max_docs_per_unit,
                    meta.stage,
                    pos,
                    now(),
                    meta.vault_project_id,
                ),
            )
            table_id = int(cur.lastrowid)
            _provenance(conn, "table", table_id, "create", source_type, actor, {"name": table})
        else:
            table_id = int(trow["id"])
            if table_meta is not None:
                conn.execute(
                    """UPDATE review_table SET review_unit=COALESCE(?, review_unit),
                           platform=?, grouping_enabled=?, max_docs_per_unit=COALESCE(?, max_docs_per_unit),
                           stage=COALESCE(?, stage), position=COALESCE(?, position),
                           vault_project_id=COALESCE(?, vault_project_id) WHERE id=?""",
                    (
                        meta.review_unit,
                        meta.platform,
                        int(meta.grouping_enabled),
                        meta.max_docs_per_unit,
                        meta.stage,
                        meta.position,
                        meta.vault_project_id,
                        table_id,
                    ),
                )

        existing = {
            c["name"].lower(): c for c in table_columns(conn, table_id, include_retired=True)
        }
        touched_ids: list[int] = []
        for rec in accepted:
            opts = (
                json.dumps([o.strip() for o in rec.configured_options])
                if rec.configured_options
                else None
            )
            ex = existing.get(rec.name.lower())
            if ex is None:
                cur = conn.execute(
                    """INSERT INTO column_def (table_id, name, position, native_type, configured_options,
                           purpose, role, concept, status, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        table_id,
                        rec.name,
                        rec.position,
                        rec.native_type,
                        opts,
                        rec.purpose,
                        rec.role,
                        rec.concept,
                        rec.status or "draft",
                        now(),
                    ),
                )
                col_id = int(cur.lastrowid)
                pv = _new_prompt_version(
                    conn,
                    col_id,
                    rec.prompt_text,
                    change_note or f"Ingested from {source_type}",
                    None,
                )
                created.append(rec.name)
                _provenance(
                    conn, "column", col_id, "create", source_type, actor, {"version": pv["version"]}
                )
            else:
                col_id = int(ex["id"])
                conn.execute(
                    """UPDATE column_def SET position=?, native_type=?, configured_options=?,
                           purpose=COALESCE(?, purpose), role=COALESCE(?, role), concept=COALESCE(?, concept),
                           status=COALESCE(?, status), retired_at=NULL WHERE id=?""",
                    (
                        rec.position,
                        rec.native_type,
                        opts,
                        rec.purpose,
                        rec.role,
                        rec.concept,
                        rec.status,
                        col_id,
                    ),
                )
                if ex["status"] == "retired" and rec.status is None:
                    conn.execute("UPDATE column_def SET status='draft' WHERE id=?", (col_id,))
                cur_pv = current_prompt(conn, col_id)
                if cur_pv is None or cur_pv["text"] != rec.prompt_text:
                    pv = _new_prompt_version(
                        conn,
                        col_id,
                        rec.prompt_text,
                        change_note or f"Re-ingested from {source_type}; text changed",
                        None,
                    )
                    new_versions.append(
                        {
                            "column": rec.name,
                            "version": pv["version"],
                            "previous": cur_pv["version"] if cur_pv else None,
                        }
                    )
                    _provenance(
                        conn,
                        "column",
                        col_id,
                        "version",
                        source_type,
                        actor,
                        {"version": pv["version"]},
                    )
                else:
                    unchanged.append(rec.name)
            touched_ids.append(col_id)

        # Dependencies are resolved after every record is stored so forward references resolve.
        for rec in accepted:
            col = get_column(conn, table_id, rec.name)
            resolved, unresolved = rebuild_intra_refs(
                conn, table_id, int(col["id"]), rec.upstream_refs
            )
            for u in unresolved:
                findings.append(
                    Finding(
                        "REF_UNRESOLVED",
                        "column",
                        int(col["id"]),
                        rec.name,
                        f"The reference `@{u}` does not match any column in the table.",
                        {"table": table, "reference": u},
                    )
                )
            if rec.advisory_upstream:
                findings.extend(
                    _set_advisory(conn, matter_id, int(col["id"]), rec.name, rec.advisory_upstream)
                )

        # Columns stored earlier but absent from this ingest are reported, never retired silently.
        submitted = {r.name.lower() for r in accepted}
        for nm, ex in existing.items():
            if nm not in submitted and ex["status"] != "retired":
                findings.append(
                    Finding(
                        "COLUMN_ABSENT_FROM_INGEST",
                        "column",
                        int(ex["id"]),
                        ex["name"],
                        "This stored column was not among the submitted records; it remains unchanged.",
                        {"table": table, "status": ex["status"]},
                    )
                )

        instr_result = None
        if table_instructions is not None:
            instr_result = _set_instructions(
                conn, table_id, table_instructions, change_note, source_type, actor
            )

        # Table-level parameter bindings fan out to every column, including ones just created.
        from .parameters import rebuild_all_parameter_edges

        rebuild_all_parameter_edges(conn, matter_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # Lint every stored column in the table (existing refs may now resolve or break).
    for col in table_columns(conn, table_id):
        cf = lint_column(conn, col)
        # Ingest already reported unresolved refs for submitted columns; keep lint's other codes.
        findings.extend(
            f for f in cf if not (f.code == "REF_UNRESOLVED" and col["name"].lower() in submitted)
        )

    return {
        "matter": m["name"],
        "table": table,
        "table_id": table_id,
        "created": created,
        "new_versions": new_versions,
        "unchanged": unchanged,
        "skipped": [r.name for r in columns if r not in accepted],
        "table_instructions": instr_result,
        "column_count": len(table_columns(conn, table_id)),
        "findings": findings,
    }


def _set_instructions(
    conn: sqlite3.Connection,
    table_id: int,
    text: str,
    change_note: str | None,
    source_type: str,
    actor: str | None,
) -> dict[str, Any]:
    cur = current_instructions(conn, table_id)
    if cur is not None and cur["text"] == text:
        return {"version": int(cur["version"]), "changed": False}
    version = int(cur["version"]) + 1 if cur else 1
    conn.execute("UPDATE table_instructions SET is_current=0 WHERE table_id=?", (table_id,))
    ins = conn.execute(
        """INSERT INTO table_instructions (table_id, version, text, change_note, created_at, is_current)
           VALUES (?,?,?,?,?,1)""",
        (table_id, version, text, change_note, now()),
    )
    _provenance(
        conn, "table_instructions", ins.lastrowid, "set", source_type, actor, {"version": version}
    )
    return {"version": version, "changed": True, "char_count": len(text)}


def table_instructions_set(
    conn: sqlite3.Connection,
    matter: str,
    table: str,
    text: str,
    change_note: str | None = None,
    source_type: str = "chat",
    actor: str | None = None,
) -> dict[str, Any]:
    m = get_matter(conn, matter)
    t = get_table(conn, int(m["id"]), table)
    conn.execute("BEGIN")
    try:
        res = _set_instructions(conn, int(t["id"]), text, change_note, source_type, actor)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    findings: list[Finding] = []
    vocab_missing = [v for v in FALLBACK_VOCABULARY if v.lower() not in text.lower()]
    if vocab_missing:
        findings.append(
            Finding(
                "INSTRUCTIONS_VOCABULARY_INCOMPLETE",
                "table",
                int(t["id"]),
                t["name"],
                "The Table Instructions do not list every controlled fallback state.",
                {"missing": vocab_missing},
            )
        )
    return {"matter": m["name"], "table": t["name"], **res, "findings": findings}


# ---------------------------------------------------------------------------
# Revise
# ---------------------------------------------------------------------------


def column_revise(
    conn: sqlite3.Connection,
    matter: str,
    table: str,
    column: str,
    prompt_text: str | None = None,
    change_note: str | None = None,
    failure_class_addressed: str | None = None,
    status: str | None = None,
    rename_to: str | None = None,
    purpose: str | None = None,
    role: str | None = None,
    concept: str | None = None,
    native_type: str | None = None,
    configured_options: list[str] | None = None,
    bump: str = "minor",
    advisory_upstream: list[Any] | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    from .constants import FAILURE_CLASS_ALIASES, FAILURE_CLASSES

    m = get_matter(conn, matter)
    t = get_table(conn, int(m["id"]), table)
    c = get_column(conn, int(t["id"]), column)
    col_id = int(c["id"])
    findings: list[Finding] = []
    changes: dict[str, Any] = {}

    status, role, bump = fold(status), fold(role), fold(bump) or "minor"
    if status is not None and status not in COLUMN_STATUSES:
        raise PromptGraphError(f"status must be one of {', '.join(COLUMN_STATUSES)}.")
    if role is not None and role not in COLUMN_ROLES:
        raise PromptGraphError(f"role must be one of {', '.join(COLUMN_ROLES)}.")
    if native_type is not None:
        native_type = NATIVE_TYPE_ALIASES.get(native_type.strip().lower(), native_type.strip())
        if native_type not in NATIVE_TYPES:
            raise PromptGraphError(f"native_type must be one of {', '.join(NATIVE_TYPES)}.")
    if failure_class_addressed is not None:
        key = failure_class_addressed.strip().lower()
        failure_class_addressed = FAILURE_CLASS_ALIASES.get(
            key, key.replace(" ", "_").replace("-", "_")
        )
        if failure_class_addressed not in FAILURE_CLASSES:
            findings.append(
                Finding(
                    "FAILURE_CLASS_INVALID",
                    "column",
                    col_id,
                    c["name"],
                    f"'{failure_class_addressed}' is not one of the skill's failure classes.",
                    {"accepted": list(FAILURE_CLASSES)},
                )
            )
            failure_class_addressed = None

    conn.execute("BEGIN")
    try:
        if rename_to is not None and _norm(rename_to).lower() != c["name"].lower():
            new_name = _norm(rename_to)
            clash = conn.execute(
                "SELECT 1 FROM column_def WHERE table_id=? AND name=?", (int(t["id"]), new_name)
            ).fetchone()
            if clash:
                raise PromptGraphError(f"A column named '{new_name}' already exists in this table.")
            conn.execute("UPDATE column_def SET name=? WHERE id=?", (new_name, col_id))
            changes["renamed_from"] = c["name"]
            _provenance(
                conn, "column", col_id, "rename", "chat", actor, {"from": c["name"], "to": new_name}
            )
        if status is not None:
            conn.execute(
                "UPDATE column_def SET status=?, retired_at=? WHERE id=?",
                (status, now() if status == "retired" else None, col_id),
            )
            changes["status"] = status
        if purpose is not None:
            conn.execute("UPDATE column_def SET purpose=? WHERE id=?", (purpose, col_id))
            changes["purpose"] = purpose
        if role is not None:
            conn.execute("UPDATE column_def SET role=? WHERE id=?", (role, col_id))
            changes["role"] = role
        if concept is not None:
            conn.execute("UPDATE column_def SET concept=? WHERE id=?", (concept, col_id))
            changes["concept"] = concept
        if native_type is not None:
            conn.execute("UPDATE column_def SET native_type=? WHERE id=?", (native_type, col_id))
            changes["native_type"] = native_type
        if configured_options is not None:
            conn.execute(
                "UPDATE column_def SET configured_options=? WHERE id=?",
                (json.dumps([o.strip() for o in configured_options]), col_id),
            )
            changes["configured_options"] = configured_options
        new_pv = None
        cur_pv = current_prompt(conn, col_id)
        if prompt_text is not None and (cur_pv is None or cur_pv["text"] != prompt_text):
            new_pv = _new_prompt_version(
                conn, col_id, prompt_text, change_note, failure_class_addressed, bump
            )
            changes["version"] = new_pv["version"]
            _provenance(
                conn,
                "column",
                col_id,
                "version",
                "chat",
                actor,
                {"version": new_pv["version"], "note": change_note},
            )
        elif prompt_text is not None:
            changes["version"] = cur_pv["version"]
            changes["text_unchanged"] = True
        if new_pv is not None or rename_to is not None:
            _, unresolved = rebuild_intra_refs(conn, int(t["id"]), col_id)
            for u in unresolved:
                findings.append(
                    Finding(
                        "REF_UNRESOLVED",
                        "column",
                        col_id,
                        rename_to or c["name"],
                        f"The reference `@{u}` does not match any column in the table.",
                        {"reference": u},
                    )
                )
        if advisory_upstream is not None:
            findings.extend(
                _set_advisory(conn, int(m["id"]), col_id, rename_to or c["name"], advisory_upstream)
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    col = conn.execute("SELECT * FROM column_def WHERE id=?", (col_id,)).fetchone()

    if "renamed_from" in changes:
        # Other prompts that referenced the old name are now unresolved; report, never rewrite.
        old = changes["renamed_from"]
        for other in table_columns(conn, int(t["id"])):
            if int(other["id"]) == col_id:
                continue
            pv = current_prompt(conn, int(other["id"]))
            if pv and f"@{old}".lower() in pv["text"].lower():
                findings.append(
                    Finding(
                        "REF_UNRESOLVED",
                        "column",
                        int(other["id"]),
                        other["name"],
                        f"The prompt still references `@{old}`, which was renamed to `{col['name']}`.",
                        {"reference": old, "renamed_to": col["name"]},
                    )
                )
                rebuild_intra_refs(conn, int(t["id"]), int(other["id"]))
    if status == "retired":
        deps = conn.execute(
            """SELECT d.kind, c.name AS column_name, rt.name AS table_name FROM dependency d
               JOIN column_def c ON c.id=d.to_column_id JOIN review_table rt ON rt.id=c.table_id
               WHERE d.from_column_id=? AND c.status!='retired'""",
            (col_id,),
        ).fetchall()
        for d in deps:
            findings.append(
                Finding(
                    "DEPENDENCY_ON_RETIRED",
                    "column",
                    col_id,
                    col["name"],
                    f"'{d['column_name']}' in table '{d['table_name']}' depends on this column, which is now retired.",
                    {
                        "kind": d["kind"],
                        "dependent_table": d["table_name"],
                        "dependent_column": d["column_name"],
                    },
                )
            )
    findings.extend(lint_column(conn, col))
    return {
        "matter": m["name"],
        "table": t["name"],
        "column": col["name"],
        "column_id": col_id,
        "changes": changes,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Read / find
# ---------------------------------------------------------------------------


def column_summary(conn: sqlite3.Connection, col: sqlite3.Row) -> dict[str, Any]:
    pv = current_prompt(conn, int(col["id"]))
    t = conn.execute("SELECT name FROM review_table WHERE id=?", (col["table_id"],)).fetchone()
    return {
        "column_id": int(col["id"]),
        "table": t["name"],
        "name": col["name"],
        "position": int(col["position"]),
        "native_type": col["native_type"],
        "status": col["status"],
        "role": col["role"],
        "concept": col["concept"],
        "purpose": col["purpose"],
        "version": pv["version"] if pv else None,
        "char_count": int(pv["char_count"]) if pv else 0,
    }


def _deps_for(
    conn: sqlite3.Connection, col_id: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    up = conn.execute(
        """SELECT d.kind, d.note, c.id AS cid, c.name AS column_name, rt.name AS table_name, c.status
           FROM dependency d JOIN column_def c ON c.id=d.from_column_id
           JOIN review_table rt ON rt.id=c.table_id WHERE d.to_column_id=? ORDER BY rt.position, c.position""",
        (col_id,),
    ).fetchall()
    down = conn.execute(
        """SELECT d.kind, d.note, c.id AS cid, c.name AS column_name, rt.name AS table_name, c.status
           FROM dependency d JOIN column_def c ON c.id=d.to_column_id
           JOIN review_table rt ON rt.id=c.table_id WHERE d.from_column_id=? ORDER BY rt.position, c.position""",
        (col_id,),
    ).fetchall()

    def fmt(r: sqlite3.Row) -> dict[str, Any]:
        return {
            "table": r["table_name"],
            "column": r["column_name"],
            "kind": r["kind"],
            "status": r["status"],
            "note": r["note"],
        }

    return [fmt(r) for r in up], [fmt(r) for r in down]


def column_read(
    conn: sqlite3.Connection,
    matter: str,
    table: str,
    column: str,
    include_history: bool = False,
) -> dict[str, Any]:
    from . import evaluation, graph

    m = get_matter(conn, matter)
    t = get_table(conn, int(m["id"]), table)
    c = get_column(conn, int(t["id"]), column)
    col_id = int(c["id"])
    pv = current_prompt(conn, col_id)
    up, down = _deps_for(conn, col_id)
    params = conn.execute(
        """SELECT sp.name, sp.value, sp.status, pb.binding_site FROM parameter_binding pb
           JOIN shared_parameter sp ON sp.id=pb.parameter_id
           WHERE pb.consuming_table_id=? AND (pb.consuming_column_id=? OR pb.consuming_column_id IS NULL)""",
        (int(t["id"]), col_id),
    ).fetchall()
    sourced = conn.execute(
        "SELECT name, value, status FROM shared_parameter WHERE source_column_id=?", (col_id,)
    ).fetchall()
    out: dict[str, Any] = {
        **column_summary(conn, c),
        "configured_options": _options(c),
        "prompt_text": pv["text"] if pv else None,
        "version_created_at": pv["created_at"] if pv else None,
        "upstream": up,
        "downstream": down,
        "consumes_parameters": [dict(p) for p in params],
        "sources_parameters": [dict(p) for p in sourced],
        "staleness": graph.column_staleness(conn, col_id),
        "evaluation": evaluation.column_eval_summary(conn, col_id),
    }
    if include_history:
        out["history"] = [
            {
                "version": r["version"],
                "created_at": r["created_at"],
                "change_note": r["change_note"],
                "failure_class_addressed": r["failure_class_addressed"],
                "char_count": int(r["char_count"]),
                "is_current": bool(r["is_current"]),
                "text": r["text"],
            }
            for r in conn.execute(
                "SELECT * FROM prompt_version WHERE column_id=? ORDER BY major, minor", (col_id,)
            )
        ]
        out["change_log"] = [
            {
                "action": r["action"],
                "at": r["at"],
                "actor": r["actor"],
                "source": r["source_type"],
                "detail": json.loads(r["detail"] or "{}"),
            }
            for r in conn.execute(
                "SELECT * FROM provenance WHERE entity_type='column' AND entity_id=? ORDER BY at, id",
                (col_id,),
            )
        ]
    return out


def concept_set(
    conn: sqlite3.Connection,
    matter: str,
    concept: str | None,
    names: list[str] | None = None,
    columns: list[dict[str, str]] | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Tag columns with a shared concept, in bulk.

    `names` tags every active column with those names across the whole matter, which is how a
    reported cluster is accepted in one call. `columns` takes explicit {table, column} pairs
    when only some of a cluster belongs together.

    Tagging does not silence a finding, it confirms it. Once tagged, the pair leaves the
    name-similarity heuristic and enters the explicit path, where a genuine difference in names,
    types or fallback states is still reported, now as fact rather than inference. Renaming the
    columns is what resolves it.

    To dismiss a false positive, give each side its own concept. Both leave the heuristic and
    neither groups with the other.
    """
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    tag = (concept or "").strip() or None

    targets: list[sqlite3.Row] = []
    unknown: list[str] = []
    if names:
        for n in names:
            rows = conn.execute(
                """SELECT c.id, c.name, rt.name AS table_name FROM column_def c
                   JOIN review_table rt ON rt.id = c.table_id
                   WHERE rt.matter_id = ? AND lower(c.name) = lower(?) AND c.retired_at IS NULL""",
                (matter_id, _norm(n)),
            ).fetchall()
            if not rows:
                unknown.append(n)
            targets.extend(rows)
    for ref in columns or []:
        t = get_table(conn, matter_id, ref["table"])
        try:
            c = get_column(conn, int(t["id"]), ref["column"])
        except PromptGraphError:
            unknown.append(f"{ref['table']} / {ref['column']}")
            continue
        targets.append(
            conn.execute(
                """SELECT c.id, c.name, rt.name AS table_name FROM column_def c
                   JOIN review_table rt ON rt.id = c.table_id WHERE c.id = ?""",
                (int(c["id"]),),
            ).fetchone()
        )
    if not targets:
        raise PromptGraphError(
            "No columns matched. Pass `names` (every column with that name) or `columns` "
            "([{table, column}])."
        )

    seen: set[int] = set()
    changed: list[str] = []
    for row in targets:
        cid = int(row["id"])
        if cid in seen:
            continue
        seen.add(cid)
        conn.execute("UPDATE column_def SET concept=? WHERE id=?", (tag, cid))
        changed.append(f"{row['table_name']} / {row['name']}")
        _provenance(conn, "column", cid, "concept", "chat", actor, {"concept": tag})
    return {
        "matter": m["name"],
        "concept": tag,
        "tagged": sorted(changed),
        "count": len(changed),
        "unknown": unknown,
        "findings": [],
    }


def columns_find(
    conn: sqlite3.Connection,
    matter: str,
    table: str | None = None,
    native_type: str | None = None,
    status: str | None = None,
    failure_class: str | None = None,
    consumes_parameter: str | None = None,
    stale: bool | None = None,
    name_contains: str | None = None,
    role: str | None = None,
    concept: str | None = None,
    include_retired: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    from . import evaluation, graph

    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    status, role = fold(status), fold(role)
    sql = """SELECT c.* FROM column_def c JOIN review_table rt ON rt.id=c.table_id
             WHERE rt.matter_id=?"""
    args: list[Any] = [matter_id]
    if table:
        t = get_table(conn, matter_id, table)
        sql += " AND c.table_id=?"
        args.append(int(t["id"]))
    if native_type:
        sql += " AND c.native_type=?"
        args.append(NATIVE_TYPE_ALIASES.get(native_type.strip().lower(), native_type.strip()))
    if status:
        sql += " AND c.status=?"
        args.append(status)
    elif not include_retired:
        sql += " AND c.status!='retired'"
    if role:
        sql += " AND c.role=?"
        args.append(role)
    if concept:
        sql += " AND lower(c.concept)=lower(?)"
        args.append(concept)
    if name_contains:
        sql += " AND lower(c.name) LIKE ?"
        args.append(f"%{name_contains.lower()}%")
    if consumes_parameter:
        p = get_parameter(conn, matter_id, consumes_parameter)
        sql += """ AND EXISTS (SELECT 1 FROM parameter_binding pb WHERE pb.parameter_id=?
                   AND pb.consuming_table_id=c.table_id
                   AND (pb.consuming_column_id=c.id OR pb.consuming_column_id IS NULL))"""
        args.append(int(p["id"]))
    sql += " ORDER BY rt.position, rt.name, c.position"
    rows = conn.execute(sql, args).fetchall()

    stale_map = graph.staleness_map(conn, matter_id) if stale is not None else {}
    out: list[dict[str, Any]] = []
    for r in rows:
        cid = int(r["id"])
        if failure_class:
            if not evaluation.column_has_open_failure_class(conn, cid, failure_class):
                continue
        if stale is not None:
            st = stale_map.get(cid, {}).get("state")
            is_stale = st in ("direct", "transitive")
            if is_stale != stale:
                continue
        s = column_summary(conn, r)
        if stale is not None:
            s["staleness"] = stale_map.get(cid)
        if failure_class:
            s["open_failures"] = evaluation.column_eval_summary(conn, cid)["open_failures"]
        out.append(s)
    total = len(out)
    page = out[offset : offset + limit]
    return {
        "matter": m["name"],
        "count": len(page),
        "total": total,
        "offset": offset,
        "truncated": offset + len(page) < total,
        "columns": page,
    }
