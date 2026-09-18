"""SQLite connection and versioned schema migrations.

One database file, WAL mode, path from PROMPT_GRAPH_DB (default ~/.prompt-graph/prompt-graph.db).
Migrations are plain SQL scripts applied in order and recorded in `schema_version`.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .constants import (
    COVERAGE_DIMENSIONS,
    DEFAULT_DATE_PATTERN,
    DEFAULT_EVIDENCE_BOUNDARY,
    FALLBACK_VOCABULARY,
)

ENV_VAR = "PROMPT_GRAPH_DB"
DEFAULT_PATH = Path.home() / ".prompt-graph" / "prompt-graph.db"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def db_path() -> Path:
    raw = os.environ.get(ENV_VAR)
    return Path(raw).expanduser() if raw else DEFAULT_PATH


# ---------------------------------------------------------------------------
# Migrations: (version, sql). Append only; never edit an applied version.
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
CREATE TABLE schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE matter (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    objective   TEXT,
    side        TEXT CHECK (side IN ('buy','sell') OR side IS NULL),
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL
);

CREATE TABLE standard (
    id                          INTEGER PRIMARY KEY,
    scope                       TEXT NOT NULL CHECK (scope IN ('firm','matter')),
    matter_id                   INTEGER REFERENCES matter(id),
    version                     INTEGER NOT NULL,
    fallback_vocabulary         TEXT NOT NULL,          -- json list
    naming_rules                TEXT,
    date_pattern                TEXT,
    currency_pattern            TEXT,
    default_evidence_boundary   TEXT,
    entities                    TEXT NOT NULL DEFAULT '[]',  -- json list of {name, jurisdiction, role, is_subject}
    objective                   TEXT,
    conventions                 TEXT NOT NULL DEFAULT '[]',  -- json list of strings
    change_note                 TEXT,
    created_at                  TEXT NOT NULL,
    is_current                  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_standard_scope ON standard(scope, matter_id, is_current);

CREATE TABLE review_table (
    id                  INTEGER PRIMARY KEY,
    matter_id           INTEGER NOT NULL REFERENCES matter(id),
    name                TEXT NOT NULL COLLATE NOCASE,
    review_unit         TEXT,
    platform            TEXT NOT NULL DEFAULT 'harvey',
    grouping_enabled    INTEGER NOT NULL DEFAULT 0,
    max_docs_per_unit   INTEGER,
    stage               TEXT,
    position            INTEGER,
    created_at          TEXT NOT NULL,
    UNIQUE (matter_id, name)
);

CREATE TABLE table_instructions (
    id          INTEGER PRIMARY KEY,
    table_id    INTEGER NOT NULL REFERENCES review_table(id),
    version     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    change_note TEXT,
    created_at  TEXT NOT NULL,
    is_current  INTEGER NOT NULL DEFAULT 1,
    UNIQUE (table_id, version)
);

CREATE TABLE column_def (
    id                  INTEGER PRIMARY KEY,
    table_id            INTEGER NOT NULL REFERENCES review_table(id),
    name                TEXT NOT NULL COLLATE NOCASE,
    position            INTEGER NOT NULL,
    native_type         TEXT NOT NULL,
    configured_options  TEXT,       -- json list, Classify only
    purpose             TEXT,
    role                TEXT,       -- orientation|extraction|validation|reconciliation|human_review
    concept             TEXT,       -- optional shared concept tag for cross-table comparison
    status              TEXT NOT NULL DEFAULT 'draft',
    created_at          TEXT NOT NULL,
    retired_at          TEXT,
    UNIQUE (table_id, name)
);
CREATE INDEX idx_column_table ON column_def(table_id, position);

CREATE TABLE prompt_version (
    id                      INTEGER PRIMARY KEY,
    column_id               INTEGER NOT NULL REFERENCES column_def(id),
    version                 TEXT NOT NULL,
    major                   INTEGER NOT NULL,
    minor                   INTEGER NOT NULL,
    text                    TEXT NOT NULL,
    char_count              INTEGER NOT NULL,
    change_note             TEXT,
    failure_class_addressed TEXT,
    created_at              TEXT NOT NULL,
    is_current              INTEGER NOT NULL DEFAULT 1,
    UNIQUE (column_id, major, minor)
);
CREATE INDEX idx_prompt_version_current ON prompt_version(column_id, is_current);

CREATE TABLE dependency (
    id              INTEGER PRIMARY KEY,
    from_column_id  INTEGER NOT NULL REFERENCES column_def(id),   -- upstream
    to_column_id    INTEGER NOT NULL REFERENCES column_def(id),   -- downstream
    kind            TEXT NOT NULL CHECK (kind IN ('intra_table_ref','cross_table_parameter','advisory')),
    declared_by     TEXT NOT NULL,
    parameter_id    INTEGER,
    note            TEXT,
    UNIQUE (from_column_id, to_column_id, kind)
);
CREATE INDEX idx_dependency_from ON dependency(from_column_id);
CREATE INDEX idx_dependency_to ON dependency(to_column_id);

CREATE TABLE shared_parameter (
    id                  INTEGER PRIMARY KEY,
    matter_id           INTEGER NOT NULL REFERENCES matter(id),
    name                TEXT NOT NULL COLLATE NOCASE,
    value               TEXT,
    source_column_id    INTEGER REFERENCES column_def(id),
    source_table_id     INTEGER REFERENCES review_table(id),
    resolved_at         TEXT,
    status              TEXT NOT NULL DEFAULT 'unresolved'
                        CHECK (status IN ('unresolved','resolved','contested')),
    note                TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (matter_id, name)
);

CREATE TABLE parameter_binding (
    id                  INTEGER PRIMARY KEY,
    parameter_id        INTEGER NOT NULL REFERENCES shared_parameter(id),
    consuming_table_id  INTEGER NOT NULL REFERENCES review_table(id),
    consuming_column_id INTEGER REFERENCES column_def(id),
    binding_site        TEXT NOT NULL CHECK (binding_site IN ('table_instructions','column_prompt')),
    UNIQUE (parameter_id, consuming_table_id, consuming_column_id, binding_site)
);

CREATE TABLE run (
    id          INTEGER PRIMARY KEY,
    table_id    INTEGER NOT NULL REFERENCES review_table(id),
    started_at  TEXT NOT NULL,
    note        TEXT,
    evaluator   TEXT,
    corpus_note TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_run_table ON run(table_id, started_at);

CREATE TABLE run_snapshot (
    run_id                  INTEGER NOT NULL REFERENCES run(id),
    column_id               INTEGER NOT NULL REFERENCES column_def(id),
    prompt_version_id       INTEGER NOT NULL REFERENCES prompt_version(id),
    instructions_version_id INTEGER REFERENCES table_instructions(id),
    PRIMARY KEY (run_id, column_id)
);

CREATE TABLE coverage_dimension (
    key                 TEXT PRIMARY KEY,
    label               TEXT NOT NULL,
    position            INTEGER NOT NULL,
    requires_grouping   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE run_coverage (
    run_id          INTEGER NOT NULL REFERENCES run(id),
    dimension_key   TEXT NOT NULL REFERENCES coverage_dimension(key),
    PRIMARY KEY (run_id, dimension_key)
);

CREATE TABLE eval_result (
    id                  INTEGER PRIMARY KEY,
    run_id              INTEGER NOT NULL REFERENCES run(id),
    column_id           INTEGER NOT NULL REFERENCES column_def(id),
    test_document       TEXT NOT NULL,
    prompt_version      TEXT,
    actual_answer       TEXT,
    evidence_relied_on  TEXT,
    expected_behavior   TEXT,
    passed              INTEGER NOT NULL,
    failure_class       TEXT,
    error_type          TEXT,
    revision_note       TEXT,
    rerun_scope         TEXT,
    result_after_rerun  TEXT,
    regressions         TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_eval_column ON eval_result(column_id, test_document);
CREATE INDEX idx_eval_run ON eval_result(run_id);

CREATE TABLE memo_outline (
    id          INTEGER PRIMARY KEY,
    matter_id   INTEGER NOT NULL REFERENCES matter(id),
    name        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    is_current  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE memo_section (
    id          INTEGER PRIMARY KEY,
    outline_id  INTEGER NOT NULL REFERENCES memo_outline(id),
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL
);

CREATE TABLE memo_assertion (
    id          INTEGER PRIMARY KEY,
    section_id  INTEGER NOT NULL REFERENCES memo_section(id),
    text        TEXT NOT NULL,
    position    INTEGER NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('extraction','judgment')),
    note        TEXT
);

CREATE TABLE assertion_source (
    id              INTEGER PRIMARY KEY,
    assertion_id    INTEGER NOT NULL REFERENCES memo_assertion(id),
    column_id       INTEGER NOT NULL REFERENCES column_def(id),
    note            TEXT,
    UNIQUE (assertion_id, column_id)
);

CREATE TABLE provenance (
    id          INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id   INTEGER,
    action      TEXT NOT NULL,
    source_type TEXT,
    actor       TEXT,
    at          TEXT NOT NULL,
    detail      TEXT
);
CREATE INDEX idx_provenance_entity ON provenance(entity_type, entity_id);
""",
    ),
    (
        2,
        """
-- Source freshness (Addendum A.1): what document set each run executed against.
ALTER TABLE matter ADD COLUMN vault_project_id TEXT;
ALTER TABLE review_table ADD COLUMN vault_project_id TEXT;

CREATE TABLE document_set_snapshot (
    id                  INTEGER PRIMARY KEY,
    matter_id           INTEGER NOT NULL REFERENCES matter(id),
    vault_project_id    TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    ready_count         INTEGER,
    latest_uploaded_at  TEXT,
    set_hash            TEXT,
    file_ids            TEXT,               -- json list of ready_to_query file ids, when enumerated
    source              TEXT NOT NULL CHECK (source IN ('harvey_api','manual')),
    note                TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_docset_project ON document_set_snapshot(matter_id, vault_project_id, observed_at);

ALTER TABLE run ADD COLUMN document_set_snapshot_id INTEGER REFERENCES document_set_snapshot(id);
""",
    ),
    (
        3,
        """
-- The requirement register (requirements/prompt-graph-requirement-register.md): the external
-- specification a suite is built to satisfy, so a playbook prompt that maps to no table is a
-- stored finding rather than a line in a spreadsheet.

CREATE TABLE requirement_source (
    id          INTEGER PRIMARY KEY,
    matter_id   INTEGER NOT NULL REFERENCES matter(id),
    name        TEXT NOT NULL,
    citation    TEXT,                    -- filename, edition, page count: what was read
    version     TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (matter_id, name)
);

CREATE TABLE requirement (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES requirement_source(id),
    ref         TEXT NOT NULL,           -- "3.4.7"
    position    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (source_id, ref)
);

-- Disposition lives on a part, not on the requirement: a quarter of a real set splits, and
-- 3.4.7 is "Part A needs an external checklist, Part B is cross-document synthesis".
CREATE TABLE requirement_part (
    id              INTEGER PRIMARY KEY,
    requirement_id  INTEGER NOT NULL REFERENCES requirement(id),
    label           TEXT,                -- "Part A"; NULL when the requirement does not split
    position        INTEGER NOT NULL,
    disposition     TEXT NOT NULL
                    CHECK (disposition IN ('served', 'synthesis', 'external', 'unassessed')),
    reason          TEXT,                -- why external, or what the synthesis must do
    UNIQUE (requirement_id, position)
);

CREATE TABLE requirement_link (
    id          INTEGER PRIMARY KEY,
    part_id     INTEGER NOT NULL REFERENCES requirement_part(id),
    kind        TEXT NOT NULL CHECK (kind IN ('served_by', 'consumes', 'produces')),
    table_id    INTEGER REFERENCES review_table(id),
    section_id  INTEGER REFERENCES memo_section(id),
    note        TEXT,
    CHECK ((table_id IS NOT NULL) + (section_id IS NOT NULL) = 1),
    CHECK ((kind = 'produces') = (section_id IS NOT NULL)),
    UNIQUE (part_id, kind, table_id, section_id)
);
CREATE INDEX idx_requirement_source ON requirement(source_id, position);
CREATE INDEX idx_requirement_part ON requirement_part(requirement_id, position);
CREATE INDEX idx_requirement_link_part ON requirement_link(part_id);
CREATE INDEX idx_requirement_link_table ON requirement_link(table_id);
""",
    ),
]


def _seed_reference_data(conn: sqlite3.Connection) -> None:
    """Rows every database needs: coverage dimensions and a firm baseline from the skill."""
    for pos, (key, label, grouping) in enumerate(COVERAGE_DIMENSIONS, start=1):
        conn.execute(
            "INSERT OR IGNORE INTO coverage_dimension (key, label, position, requires_grouping)"
            " VALUES (?, ?, ?, ?)",
            (key, label, pos, int(grouping)),
        )
    exists = conn.execute(
        "SELECT 1 FROM standard WHERE scope='firm' AND is_current=1 LIMIT 1"
    ).fetchone()
    if not exists:
        conn.execute(
            """INSERT INTO standard (scope, matter_id, version, fallback_vocabulary, naming_rules,
                   date_pattern, currency_pattern, default_evidence_boundary, entities, objective,
                   conventions, change_note, created_at, is_current)
               VALUES ('firm', NULL, 1, ?, ?, ?, NULL, ?, '[]', NULL, '[]',
                       'Seeded from legal-review-table-builder skill v1', ?, 1)""",
            (
                json.dumps(list(FALLBACK_VOCABULARY)),
                "Use entity and individual names exactly as printed in the document; "
                "do not shorten, expand, or correct them.",
                DEFAULT_DATE_PATTERN,
                DEFAULT_EVIDENCE_BOUNDARY,
                now(),
            ),
        )


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the database, enable WAL, apply pending migrations."""
    target = Path(path).expanduser() if path else db_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(target) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn)
    return conn


def connect_readonly(
    path: str | os.PathLike[str] | None = None, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open the database read-only, for a second process that must never write to it.

    The MCP server is the only writer. A reader that called `connect()` would run migrations
    and seed reference rows, writing to a client-data database from a process that has no
    business doing so; SQLite refuses writes on this connection instead. WAL allows this
    reader to run concurrently with the writer, and each statement sees the latest commit.
    """
    target = (Path(path).expanduser() if path else db_path()).resolve()
    if not target.exists():
        raise FileNotFoundError(f"No prompt-graph database at {target}")
    # Build the URI with as_uri() rather than interpolating the path. On Windows a raw path is
    # `C:\Users\...`, and SQLite's URI parser wants forward slashes, so the interpolated form
    # fails there: the MCP server (which opens a plain path) would work while the read API, and
    # so the whole UI, would not start. as_uri() also percent-encodes a path containing ? or #.
    conn = sqlite3.connect(
        f"{target.as_uri()}?mode=ro",
        uri=True,
        isolation_level=None,
        check_same_thread=check_same_thread,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def data_version(conn: sqlite3.Connection) -> int:
    """Changes whenever *another* connection commits.

    The counter is per connection, so this is only meaningful on a connection that outlives
    the writes it is watching. A fresh connection per call returns a constant and detects
    nothing; see `api._version_conn`.
    """
    return int(conn.execute("PRAGMA data_version").fetchone()[0])


def current_version(conn: sqlite3.Connection) -> int:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not has_table:
        return 0
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"] or 0)


def migrate(conn: sqlite3.Connection) -> list[int]:
    applied: list[int] = []
    have = current_version(conn)
    for version, sql in MIGRATIONS:
        if version <= have:
            continue
        # executescript commits any open transaction first, so the transaction lives in the script.
        script = (
            "BEGIN;\n"
            + sql
            + f"\nINSERT INTO schema_version (version, applied_at) VALUES ({version}, '{now()}');\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(version)
    conn.execute("BEGIN")
    try:
        _seed_reference_data(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return applied
