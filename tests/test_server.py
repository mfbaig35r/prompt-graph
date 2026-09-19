"""The MCP surface: tool registration, JSON-argument calls, error shape, and the demo seed."""

from __future__ import annotations

import asyncio
import json

from prompt_graph import db, seed, server
from prompt_graph.server import mcp
from tests.conftest import HARBOR

EXPECTED_TOOLS = {
    "matter_open",
    "standard_set",
    "table_ingest",
    "table_instructions_set",
    "column_revise",
    "column_read",
    "columns_find",
    "concept_set",
    "prompt_check",
    "requirement_set",
    "requirements_ingest",
    "suite_check",
    "impact_of_change",
    "staleness_report",
    "parameter_set",
    "playbook_check",
    "run_record",
    "eval_record",
    "failures_summary",
    "run_compare",
    "memo_outline_set",
    "coverage_check",
    "freshness_check",
    "table_readiness",
    "matter_export",
    "matter_import",
}


def call(tool: str, **args):
    result = asyncio.run(mcp.call_tool(tool, args))
    if isinstance(result, tuple):  # (content blocks, structured)
        return result[1]
    if isinstance(result, dict):
        return result
    return json.loads(result[0].text)


def test_tool_surface():
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert names == EXPECTED_TOOLS
    for t in mcp._tool_manager.list_tools():
        assert t.description and len(t.description) > 80, t.name


def test_call_tools_with_json_arguments(conn):
    r = call("matter_open", name="Project Delta", create=True, objective="Buy side", side="buy")
    assert r["created"] is True and r["table_count"] == 0
    r = call(
        "table_ingest",
        matter="Project Delta",
        table="Entities",
        columns=[
            {
                "name": "Type",
                "position": 1,
                "native_type": "Classify",
                "prompt_text": "## Task\n\nClassify.\n\n## Output format\n\nReturn only the exact configured option.",
                "configured_options": ["A", "B"],
            },
            {
                "name": "Detail",
                "position": 2,
                "native_type": "Free Response",
                "prompt_text": "Use @Type. Return `N/A` if silent. Return the value.",
            },
        ],
        table_instructions="## Shared rules\n\n`Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`, `Unable to determine`.",
    )
    assert r["created"] == ["Type", "Detail"]
    assert "FALLBACK_SYNONYM" in {f["code"] for f in r["findings"]}
    assert r["finding_count"] == len(r["findings"])
    r = call(
        "prompt_check",
        prompt_text="Return `TBD`.",
        native_type="Date",
        matter="Project Delta",
        table="Entities",
    )
    assert {f["code"] for f in r["findings"]} == {"FALLBACK_SYNONYM"} and r[
        "references_checked"
    ] is True
    r = call("columns_find", matter="Project Delta", native_type="Classify")
    assert r["count"] == 1 and "prompt_text" not in r["columns"][0]


def test_unknown_matter_returns_error_not_exception(conn):
    r = call("column_read", matter="Nope", table="T", column="C")
    assert r["error"].startswith("No matter named 'Nope'") and r["findings"] == []


def test_seed_demo_is_idempotent_and_serialisable(conn):
    seed.load_demo(conn)
    seed.load_demo(conn)  # second load re-ingests: no duplicate columns
    assert conn.execute("SELECT COUNT(*) FROM column_def").fetchone()[0] == 18
    ov = call("matter_open", name=HARBOR)
    assert ov["table_count"] == 4 and ov["column_count"] == 18
    for name, args in [
        ("suite_check", {"matter": HARBOR}),
        ("staleness_report", {"matter": HARBOR}),
        ("impact_of_change", {"matter": HARBOR, "parameter": "Target Legal Name"}),
        ("coverage_check", {"matter": HARBOR}),
        ("failures_summary", {"matter": HARBOR}),
        (
            "column_read",
            {
                "matter": HARBOR,
                "table": "Entity Register",
                "column": "Execution Status",
                "include_history": True,
            },
        ),
    ]:
        out = call(name, **args)
        assert "error" not in out, (name, out.get("error"))
        json.dumps(out)


def test_database_file_uses_wal_and_env_path(tmp_path, monkeypatch):
    path = tmp_path / "pg.db"
    monkeypatch.setenv(db.ENV_VAR, str(path))
    c = db.connect()
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.current_version(c) == 3
    assert c.execute("SELECT COUNT(*) FROM coverage_dimension").fetchone()[0] == 14
    assert c.execute("SELECT scope FROM standard").fetchone()[0] == "firm"
    c.close()
    c2 = db.connect()  # reopening applies nothing and keeps the firm baseline single
    assert db.migrate(c2) == []
    assert c2.execute("SELECT COUNT(*) FROM standard").fetchone()[0] == 1
    c2.close()


def test_cli_seed_demo(tmp_path, capsys):
    path = tmp_path / "demo.db"
    server.main(["--db", str(path), "--seed-demo"])
    assert "seeded 'Project Harbor' with 4 tables" in capsys.readouterr().err
    server.main(["--db", str(path), "--migrate"])
    assert "schema version 3" in capsys.readouterr().err
