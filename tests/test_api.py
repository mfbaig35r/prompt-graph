"""Smoke tests for the read-only HTTP layer.

The service functions underneath are covered by the rest of the suite. What was not exercised
anywhere is the HTTP wrapper itself: that every route is reachable and serialises, that a bad
name is a 404 rather than a 500, that a missing database is a 503, that the connection really
does refuse writes, and that the data_version watcher's module-level connection works. A
refactor in api.py fails silently until someone opens the UI; these catch it in CI instead.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="the 'ui' extra is not installed")
from fastapi.testclient import TestClient  # noqa: E402

from prompt_graph import api, db, seed  # noqa: E402

DEMO = "Project Harbor"


def _reset_watcher() -> None:
    """The data_version watcher is a module-level connection by design (the counter belongs to
    the connection, so a per-request one would never report a change). Left alive between tests
    it would hold a handle to a deleted temp database and leak into the next one."""
    if api._version_conn is not None:
        api._version_conn.close()
    api._version_conn = None


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    target = tmp_path / "prompt-graph.db"
    monkeypatch.setenv(db.ENV_VAR, str(target))
    writer = db.connect(target)
    seed.load_demo(writer, with_runs=True)
    writer.close()
    _reset_watcher()
    with TestClient(api.app) as c:
        yield c
    _reset_watcher()


@pytest.fixture()
def names(client: TestClient) -> dict[str, str]:
    """Discover a real table and column from the API itself, so the smoke test does not go stale
    when the demo fixture changes."""
    matter = client.get(f"/api/matters/{DEMO}").json()
    table = matter["tables"][0]["table"]
    detail = client.get(f"/api/matters/{DEMO}/tables/{table}").json()
    return {"table": table, "column": detail["columns"][0]["name"]}


def test_health_reports_the_database(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_version_returns_an_integer(client: TestClient) -> None:
    r = client.get("/api/version")
    assert r.status_code == 200
    assert isinstance(r.json()["data_version"], int)


def test_version_watcher_survives_repeat_calls(client: TestClient) -> None:
    """The watcher caches its connection in a module global. Calling twice exercises the reuse
    branch, which is the one a refactor breaks."""
    first = client.get("/api/version").json()["data_version"]
    second = client.get("/api/version").json()["data_version"]
    assert first == second


def test_matters_lists_the_demo(client: TestClient) -> None:
    r = client.get("/api/matters")
    assert r.status_code == 200
    assert DEMO in [m["name"] for m in r.json()["matters"]]


@pytest.mark.parametrize(
    "suffix",
    ["", "/concepts", "/coverage", "/requirements", "/activity"],
)
def test_matter_scoped_routes_answer(client: TestClient, suffix: str) -> None:
    r = client.get(f"/api/matters/{DEMO}{suffix}")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), dict)


def test_table_routes_answer(client: TestClient, names: dict[str, str]) -> None:
    for suffix in ("", "/graph"):
        r = client.get(f"/api/matters/{DEMO}/tables/{names['table']}{suffix}")
        assert r.status_code == 200, r.text


def test_column_route_answers(client: TestClient, names: dict[str, str]) -> None:
    r = client.get(f"/api/matters/{DEMO}/tables/{names['table']}/columns/{names['column']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == names["column"]
    assert body["prompt_text"]


def test_graph_edges_reference_real_nodes(client: TestClient, names: dict[str, str]) -> None:
    """The UI draws edges by node id. An edge pointing at a node the payload omits renders as a
    line into empty space, which is a wrong picture rather than an error."""
    g = client.get(f"/api/matters/{DEMO}/tables/{names['table']}/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["from"] in ids and e["to"] in ids, e


def test_unknown_matter_is_404(client: TestClient) -> None:
    r = client.get("/api/matters/No Such Matter")
    assert r.status_code == 404


def test_unknown_table_is_404(client: TestClient) -> None:
    r = client.get(f"/api/matters/{DEMO}/tables/No Such Table")
    assert r.status_code == 404


def test_missing_database_is_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting the API before the MCP server has ever written is the likely first-run state.
    It must say so, not fail as a server error."""
    monkeypatch.setenv(db.ENV_VAR, str(tmp_path / "absent.db"))
    _reset_watcher()
    with TestClient(api.app) as c:
        assert c.get("/api/matters").status_code == 503
        assert c.get("/api/version").status_code == 503
    _reset_watcher()


def test_the_api_connection_refuses_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The read-only posture is the reason this process may run against client data at all."""
    target = tmp_path / "prompt-graph.db"
    monkeypatch.setenv(db.ENV_VAR, str(target))
    writer = db.connect(target)
    seed.load_demo(writer, with_runs=False)
    writer.close()
    reader = db.connect_readonly()
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("delete from column_def")
    finally:
        reader.close()
