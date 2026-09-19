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


def test_readonly_uri_is_well_formed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The read-only URI is built with as_uri(), not string interpolation. A Windows path
    interpolates to `file:C:\\Users\\...`, which SQLite's URI parser rejects, and that would take
    down the read API and the UI while leaving the MCP server (a plain path) working."""
    target = tmp_path / "prompt-graph.db"
    monkeypatch.setenv(db.ENV_VAR, str(target))
    db.connect(target).close()
    uri = f"{target.resolve().as_uri()}?mode=ro"
    assert uri.startswith("file:///")
    assert "\\" not in uri
    reader = db.connect_readonly()
    try:
        assert reader.execute("select 1").fetchone()[0] == 1
    finally:
        reader.close()


def test_now_strictly_increases() -> None:
    """Windows' clock ticks about every 15ms, so rapid writes would otherwise share a
    timestamp and staleness, which compares with a strict >, would miss the change."""
    stamps = [db.now() for _ in range(500)]
    assert len(set(stamps)) == 500
    assert stamps == sorted(stamps)


# --- playbooks: files, not rows ---------------------------------------------

_MINI = """
# AI Guidance
Document control: version 1, owner Legal. On exhaustion, escalate.

## Limitation of Liability
#### Standard Position
ADD the below provision if not already addressed: "The breaching party shall be liable only
for direct damages arising out of any unauthorised disclosure."
#### Acceptable Positions
Mutual capACCEPT a mutual cap at two times fees paid.
### Guidance
Rule ID: mnda.liability.cap
### Required
Yes
"""


@pytest.fixture()
def pb_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    books = tmp_path / "books"
    books.mkdir()
    (books / "mini.md").write_text(_MINI)
    monkeypatch.setenv(api.ENV_PLAYBOOKS, str(books))
    monkeypatch.setenv(db.ENV_VAR, str(tmp_path / "pg.db"))
    db.connect(tmp_path / "pg.db").close()
    _reset_watcher()
    with TestClient(api.app) as c:
        yield c
    _reset_watcher()


def test_playbooks_are_listed_and_parsed(pb_client: TestClient) -> None:
    listing = pb_client.get("/api/playbooks")
    assert listing.status_code == 200
    assert [p["name"] for p in listing.json()["playbooks"]] == ["mini.md"]

    d = pb_client.get("/api/playbooks/mini.md").json()
    assert d["counts"]["rules"] == 1
    assert d["counts"]["with_rule_id"] == 1
    r = d["rules"][0]
    assert r["name"] == "Limitation of Liability" and r["required"] is True
    assert r["absence_remediation"] is True


def test_a_path_outside_the_configured_directory_is_refused(pb_client: TestClient) -> None:
    """The read layer opens files, so containment is the whole of its security posture."""
    for attempt in ("../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "/etc/passwd"):
        assert pb_client.get(f"/api/playbooks/{attempt}").status_code in (404, 400)


def test_without_a_configured_directory_the_routes_say_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(api.ENV_PLAYBOOKS, raising=False)
    monkeypatch.setenv(db.ENV_VAR, str(tmp_path / "pg.db"))
    db.connect(tmp_path / "pg.db").close()
    _reset_watcher()
    with TestClient(api.app) as c:
        r = c.get("/api/playbooks")
        assert r.status_code == 503 and "PROMPT_GRAPH_PLAYBOOKS" in r.text
    _reset_watcher()


def test_findings_are_attached_to_their_rule(pb_client: TestClient) -> None:
    d = pb_client.get("/api/playbooks/mini.md").json()
    codes = {f["code"] for f in d["rules"][0]["findings"]}
    assert "UNACCEPTABLE_NOT_STATED" in codes
    assert sum(len(r["findings"]) for r in d["rules"]) <= d["counts"]["findings"]
