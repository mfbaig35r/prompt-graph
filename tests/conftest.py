from __future__ import annotations

import sqlite3

import pytest

from prompt_graph import db, seed, server
from prompt_graph.models import ColumnRecord

HARBOR = "Project Harbor"


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = db.connect(":memory:")
    server.set_conn(c)
    yield c
    c.close()
    server.set_conn(None)


@pytest.fixture()
def harbor(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Demo matter without runs or the post-run revision: a clean four-table graph."""
    seed.load_demo(conn, with_runs=False)
    return conn


@pytest.fixture()
def harbor_evaluated(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Demo matter with two runs, logged failures, and one revision after the run."""
    seed.load_demo(conn, with_runs=True)
    return conn


def col(
    name: str,
    position: int,
    prompt: str,
    native_type: str = "FreeResponse",
    options: list[str] | None = None,
    **kw,
) -> ColumnRecord:
    return ColumnRecord(
        name=name,
        position=position,
        native_type=native_type,
        prompt_text=prompt,
        configured_options=options,
        **kw,
    )


CLEAN_FR = "## Task\n\nIdentify the thing.\n\n## Fallback rules\n\n- If silent, return `Not addressed`.\n\n## Output format\n\nReturn the name only."
CLEAN_CLASSIFY = "## Task\n\nClassify. Choose exactly one configured option.\n\n## Output format\n\nReturn only the exact configured option."
