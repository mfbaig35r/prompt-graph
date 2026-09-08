"""Schema and payload ergonomics: enums, descriptions, matter discovery, paging, case folding."""

from __future__ import annotations

import json

import pytest

from prompt_graph.server import (
    column_revise,
    columns_find,
    matter_open,
    mcp,
    run_record,
    standard_set,
    table_ingest,
)
from tests.conftest import CLEAN_FR, HARBOR, col
from tests.test_server import call

TOOLS = {t.name: t for t in mcp._tool_manager.list_tools()}


def _props(tool: str) -> dict:
    return TOOLS[tool].parameters["properties"]


def _enum(prop: dict) -> list | None:
    if "enum" in prop:
        return prop["enum"]
    for alt in prop.get("anyOf", []):
        if "enum" in alt:
            return alt["enum"]
    return None


@pytest.mark.parametrize(
    ("tool", "param", "values"),
    [
        ("matter_open", "side", ["buy", "sell"]),
        ("standard_set", "scope", ["firm", "matter"]),
        ("table_ingest", "source_type", ["chat", "excel", "csv", "harvey_export", "drafted"]),
        ("column_revise", "status", ["draft", "testing", "verified", "retired"]),
        (
            "column_revise",
            "role",
            ["orientation", "extraction", "validation", "reconciliation", "human_review"],
        ),
        ("column_revise", "bump", ["minor", "major"]),
        (
            "column_revise",
            "native_type",
            ["Classify", "Date", "Currency", "Number", "Duration", "Verbatim", "FreeResponse"],
        ),
        (
            "prompt_check",
            "native_type",
            ["Classify", "Date", "Currency", "Number", "Duration", "Verbatim", "FreeResponse"],
        ),
        ("columns_find", "status", ["draft", "testing", "verified", "retired"]),
        ("failures_summary", "group_by", ["class", "table", "column"]),
        ("parameter_set", "status", ["unresolved", "resolved", "contested"]),
    ],
)
def test_closed_sets_are_enums(tool, param, values):
    assert _enum(_props(tool)[param]) == values


def test_batch_model_fields_stay_soft():
    # One bad record must not reject a whole batch, so these are strings, not enums.
    schema = json.dumps(TOOLS["eval_record"].parameters)
    assert '"scope_leakage"' not in schema
    schema = json.dumps(TOOLS["table_ingest"].parameters)
    assert '"enum": ["Classify"' not in schema


def test_every_top_level_parameter_has_a_description():
    missing = [
        f"{name}.{p}"
        for name, t in TOOLS.items()
        for p, prop in t.parameters["properties"].items()
        if not prop.get("description")
    ]
    assert missing == []


def test_actor_is_described_everywhere_it_appears():
    for name, t in TOOLS.items():
        prop = t.parameters["properties"].get("actor")
        if prop is not None:
            assert "change log" in prop["description"], name


def test_matter_open_lists_without_a_name(harbor):
    r = matter_open()
    assert r["count"] == 1 and r["matters"][0]["name"] == HARBOR


def test_matter_open_does_not_create_on_a_typo(harbor):
    r = matter_open("Project Harbour")
    assert "No matter named 'Project Harbour'" in r["error"] and HARBOR in r["error"]
    assert matter_open()["count"] == 1
    r = matter_open("Project Harbour", create=True)
    assert r["created"] is True and matter_open()["count"] == 2


def test_columns_find_pages(harbor):
    first = columns_find(HARBOR, limit=5)
    assert first["count"] == 5 and first["total"] == 18 and first["truncated"] is True
    last = columns_find(HARBOR, limit=5, offset=15)
    assert last["count"] == 3 and last["truncated"] is False
    keys = [(c["table"], c["name"]) for c in first["columns"]] + [
        (c["table"], c["name"]) for c in columns_find(HARBOR, limit=13, offset=5)["columns"]
    ]
    assert len(set(keys)) == 18


def test_case_folding_on_closed_sets(conn):
    matter_open("M", create=True, side="BUY")
    table_ingest(
        "M", "T", [col("A", 1, CLEAN_FR, status="Draft", role="Orientation")], source_type="Excel"
    )
    r = column_revise(
        "M",
        "T",
        "A",
        status="Verified",
        role="Extraction",
        bump="Major",
        prompt_text=CLEAN_FR + " x",
    )
    assert r["changes"]["status"] == "verified" and r["changes"]["role"] == "extraction"
    assert r["changes"]["version"] == "v2.0"
    assert columns_find("M", status="VERIFIED")["count"] == 1
    s = standard_set("Firm", currency_pattern="USD 1,000.00")
    assert s["scope"] == "firm"
    assert matter_open("M")["side"] == "buy"


def test_case_folding_over_the_wire(conn):
    call("matter_open", name="M", create=True)
    call(
        "table_ingest",
        matter="M",
        table="T",
        columns=[
            {"name": "A", "position": 1, "native_type": "free response", "prompt_text": CLEAN_FR}
        ],
    )
    r = call("column_revise", matter="M", table="T", column="A", status="Testing")
    assert r["changes"]["status"] == "testing"


def test_run_record_reports_the_persisted_timestamp(harbor):
    r = run_record(HARBOR, "Entity Register")
    assert r["started_at"] != "now" and r["started_at"].startswith("20")
    stored = harbor.execute("SELECT started_at FROM run WHERE id=?", (r["run_id"],)).fetchone()[0]
    assert r["started_at"] == stored
    r2 = run_record(HARBOR, "Entity Register", started_at="2026-08-26T10:00:00+00:00")
    assert r2["started_at"] == "2026-08-26T10:00:00+00:00"
