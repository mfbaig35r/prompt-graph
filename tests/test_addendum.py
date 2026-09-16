"""Addendum A: source freshness (A.1), reverse coverage (A.2), export (A.3), readiness (A.4)."""

from __future__ import annotations

import json

import pytest

from prompt_graph import freshness, harvey
from prompt_graph.models import ConsumerBinding, TableMeta
from prompt_graph.server import (
    column_revise,
    coverage_check,
    freshness_check,
    impact_of_change,
    matter_export,
    matter_open,
    parameter_set,
    run_record,
    staleness_report,
    table_ingest,
    table_readiness,
)
from tests.conftest import CLEAN_CLASSIFY, CLEAN_FR, HARBOR, col

ER = "Entity Register"


def codes(res):
    return sorted(f["code"] for f in res["findings"])


# --- A.1 freshness ---------------------------------------------------------------------------


def test_no_project_means_untracked(harbor):
    r = freshness_check(HARBOR)
    assert r["counts"] == {"unobserved": 4}
    assert codes(r) == ["DOCSET_NO_PROJECT"] * 4
    assert r["harvey_api_configured"] is False


def test_manual_snapshot_with_run_then_moved(harbor):
    matter_open(HARBOR, vault_project_id="vp-1")
    r = run_record(HARBOR, ER, documents_ready=400)
    assert r["document_set"]["ready_count"] == 400 and r["document_set"]["source"] == "manual"
    fr = freshness_check(HARBOR, table=ER)
    assert fr["tables"][0]["state"] == "current"
    fr = freshness_check(HARBOR, table=ER, refresh=True, ready_count=447, note="vault index count")
    assert fr["refreshed"][0]["change_since_previous"]["ready_delta"] == 47
    assert fr["tables"][0]["state"] == "moved"
    moved = [f for f in fr["findings"] if f["code"] == "DOCSET_MOVED"]
    assert "last ran against 400 ready documents" in moved[0]["observation"]
    assert "+47" in moved[0]["observation"] and "manual observation" in moved[0]["observation"]
    # Other tables in the matter share the project but never ran.
    all_ = freshness_check(HARBOR)
    assert all_["counts"] == {"moved": 1, "never_run": 3}


def test_run_without_snapshot_is_unrecorded_then_links_latest(harbor):
    matter_open(HARBOR, vault_project_id="vp-1")
    r = run_record(HARBOR, ER)
    assert r["document_set"] is None and "DOCSET_UNRECORDED" in codes(r)
    # No snapshot exists anywhere yet, so the table is unobserved rather than unrecorded.
    assert freshness_check(HARBOR, table=ER)["tables"][0]["state"] == "unobserved"
    freshness_check(HARBOR, refresh=True, ready_count=9, vault_project_id="vp-1")
    assert freshness_check(HARBOR, table=ER)["tables"][0]["state"] == "unrecorded"
    freshness_check(HARBOR, refresh=True, ready_count=10, vault_project_id="vp-1")
    r2 = run_record(HARBOR, ER)
    assert r2["document_set"]["ready_count"] == 10  # latest snapshot linked automatically
    assert freshness_check(HARBOR, table=ER)["tables"][0]["state"] == "current"


def test_file_ids_count_additions_and_removals(harbor):
    matter_open(HARBOR, vault_project_id="vp-1")
    run_record(HARBOR, ER)  # unrecorded
    freshness_check(HARBOR, refresh=True, vault_project_id="vp-1", file_ids=["a", "b", "c"])
    run_record(HARBOR, ER)
    fr = freshness_check(
        HARBOR, refresh=True, vault_project_id="vp-1", file_ids=["a", "c", "d", "e"]
    )
    d = fr["tables"][0]["diff"]
    assert d["basis"] == "file_ids" and d["added"] == 2 and d["removed"] == 1 and d["moved"]
    assert "2 added and 1 removed" in fr["findings"][0]["observation"]


def test_table_project_overrides_matter_project(harbor):
    matter_open(HARBOR, vault_project_id="vp-matter")
    table_ingest(
        HARBOR, "Charter Documents", [], table_meta=TableMeta(vault_project_id="vp-charter")
    )
    fr = freshness_check(HARBOR, refresh=True, ready_count=5, table="Charter Documents")
    assert fr["refreshed"][0]["vault_project_id"] == "vp-charter"
    by_table = {t["table"]: t for t in freshness_check(HARBOR)["tables"]}
    assert by_table["Charter Documents"]["vault_project_id"] == "vp-charter"
    assert by_table[ER]["vault_project_id"] == "vp-matter"


def test_harvey_api_path_with_fake_fetcher(harbor, monkeypatch):
    monkeypatch.setenv(harvey.ENV_KEY, "test-key")
    calls: list[str] = []

    def fake(url, headers):
        calls.append(url)
        assert headers["Authorization"] == "Bearer test-key"
        if "cursor=" not in url:
            return {
                "files": [
                    {
                        "id": "f1",
                        "uploaded_at": "2026-09-01T00:00:00Z",
                        "processing_status": "ready_to_query",
                    },
                    {
                        "id": "f2",
                        "uploaded_at": "2026-09-02T00:00:00Z",
                        "processing_status": "processing",
                    },
                    {
                        "id": "f3",
                        "uploaded_at": "2026-09-03T00:00:00Z",
                        "deleted_at": "2026-09-04T00:00:00Z",
                    },
                ],
                "has_more": True,
                "next_cursor": "c2",
            }
        return {"files": [{"id": "f4", "uploaded_at": "2026-09-05T00:00:00Z"}], "has_more": False}

    matter_open(HARBOR, vault_project_id="vp-1")
    r = freshness.freshness_check(harbor, HARBOR, refresh=True, fetcher=fake)
    ref = r["refreshed"][0]
    assert ref["source"] == "harvey_api" and ref["requests_used"] == 2
    assert ref["snapshot"]["ready_count"] == 2  # f2 still processing, f3 deleted
    assert ref["snapshot"]["latest_uploaded_at"] == "2026-09-05T00:00:00Z"
    # A second poll inside the window is served from cache and costs no request.
    r2 = freshness.freshness_check(harbor, HARBOR, refresh=True, fetcher=fake)
    assert r2["refreshed"][0]["source"] == "cache" and len(calls) == 2
    r3 = freshness.freshness_check(harbor, HARBOR, refresh=True, force=True, fetcher=fake)
    assert r3["refreshed"][0]["source"] == "harvey_api" and len(calls) == 4


def test_harvey_unavailable_is_a_finding_not_an_exception(harbor):
    matter_open(HARBOR, vault_project_id="vp-1")
    r = freshness_check(HARBOR, refresh=True)
    assert codes(r) == ["DOCSET_UNOBSERVED"] * 4 + ["HARVEY_UNAVAILABLE"]
    assert (
        "HARVEY_API_KEY is not set"
        in [f for f in r["findings"] if f["code"] == "HARVEY_UNAVAILABLE"][0]["observation"]
    )


def test_harvey_unexpected_shape_fails_loudly(monkeypatch):
    monkeypatch.setenv(harvey.ENV_KEY, "k")
    with pytest.raises(harvey.HarveyUnavailable, match="Unexpected response shape"):
        harvey.list_ready_files("vp", fetcher=lambda u, h: {"items": []})


def test_freshness_reaches_coverage_and_overview(harbor):
    matter_open(HARBOR, vault_project_id="vp-1")
    run_record(HARBOR, "Real Estate Leases", documents_ready=100)
    freshness_check(HARBOR, refresh=True, ready_count=120, vault_project_id="vp-1")
    cov = coverage_check(HARBOR)
    a = next(
        x
        for s in cov["sections"]
        for x in s["assertions"]
        if x["assertion"].startswith("Leases requiring")
    )
    assert "document set moved since last run" in a["sources"][0]["reasons"]
    ov = matter_open(HARBOR)
    assert ov["document_sets"]["moved"] == 1
    assert (
        next(t for t in ov["tables"] if t["table"] == "Real Estate Leases")["document_set"]
        == "moved"
    )


# --- A.2 reverse coverage --------------------------------------------------------------------


def test_impact_ends_with_memo_consequences(harbor):
    r = impact_of_change(HARBOR, table="Charter Documents", column="Transfer Restrictions")
    memo = r["memo_consequences"]
    assert [m["assertion"][:20] for m in memo] == ["Transfer restriction"]
    assert memo[0]["status"] == "unsupported"  # both of its sources are in the affected set
    assert [f["code"] for f in r["findings"]] == ["MEMO_ASSERTION_AT_RISK"]
    assert "unsupported" in r["findings"][0]["observation"]


def test_weakened_when_one_source_survives(harbor):
    r = impact_of_change(HARBOR, table="Material Contracts", column="Counterparty Consent Detail")
    # A leaf still sources an assertion; its other source is untouched, so the assertion is weakened.
    assert [m["status"] for m in r["memo_consequences"]] == ["weakened"]
    r = impact_of_change(HARBOR, table="Charter Documents", column="Change of Control Consent")
    statuses = {m["assertion"][:30]: m["status"] for m in r["memo_consequences"]}
    assert statuses["Charter-level consents require"] == "unsupported"
    assert (
        statuses["Whether the proposed transacti"] == "weakened"
    )  # judgment; other input untouched
    assert (
        next(m for m in r["memo_consequences"] if m["status"] == "weakened")["kind"] == "judgment"
    )


def test_parameter_impact_and_staleness_carry_memo_consequences(harbor):
    r = impact_of_change(HARBOR, parameter="Target Legal Name")
    assert any(m["status"] == "unsupported" for m in r["memo_consequences"])
    run_record(HARBOR, "Charter Documents")
    column_revise(
        HARBOR, "Charter Documents", "Change of Control Consent", prompt_text=CLEAN_CLASSIFY
    )
    sr = staleness_report(HARBOR, table="Charter Documents")
    assert (
        sr["memo_consequences"]
        and sr["memo_consequences"][0]["sources"][0]["reason"] == "directly stale"
    )
    assert "MEMO_ASSERTION_AT_RISK" in codes(sr)


def test_freshness_memo_consequences(harbor):
    matter_open(HARBOR, vault_project_id="vp-1")
    run_record(HARBOR, "Real Estate Leases", documents_ready=1)
    fr = freshness_check(HARBOR, refresh=True, ready_count=2, vault_project_id="vp-1")
    assert fr["memo_consequences"][0]["assertion"].startswith("Leases requiring")
    assert fr["memo_consequences"][0]["sources"][0]["reason"] == "document set moved since last run"


# --- A.3 export ------------------------------------------------------------------------------


def test_export_inline_is_complete_and_serialisable(harbor_evaluated):
    r = matter_export(HARBOR, inline=True)
    doc = r["document"]
    assert doc["export_format_version"] == 1 and doc["schema_version"] == 3
    assert r["counts"]["tables"] == 4 and r["counts"]["columns"] == 18
    assert r["counts"]["prompt_versions"] == 19  # one revision in the evaluated fixture
    assert r["counts"]["runs"] == 2 and r["counts"]["eval_results"] == 10
    assert r["counts"]["parameters"] == 2 and r["counts"]["dependencies"] > 0
    assert doc["coverage"]["totals"]["assertions"] == 11
    assert (
        doc["memo_outline"]["sections"][0]["assertions"][0]["sources"][0]["column_name"]
        == "Principal Entity"
    )
    exec_status = next(
        c
        for t in doc["tables"]
        for c in t["columns"]
        if c["name"] == "Execution Status" and t["name"] == ER
    )
    assert [v["version"] for v in exec_status["prompt_versions"]] == ["v1.0", "v1.1"]
    assert any(e["action"] == "version" for e in doc["provenance"])
    json.dumps(doc)


def test_export_writes_a_file(harbor, tmp_path):
    r = matter_export(HARBOR, write_to=str(tmp_path))
    assert r["path"].startswith(str(tmp_path)) and r["path"].endswith(".json")
    on_disk = json.loads(open(r["path"]).read())
    assert on_disk["matter"]["name"] == HARBOR and r["bytes"] > 10_000
    explicit = matter_export(HARBOR, write_to=str(tmp_path / "harbor.json"))
    assert explicit["path"].endswith("harbor.json")


# --- A.4 readiness ---------------------------------------------------------------------------


def test_readiness_groups_by_cause(harbor_evaluated):
    r = table_readiness(HARBOR, ER)
    assert r["total"] == r["finding_count"] == sum(r["counts"].values())
    assert set(r["counts"]) == {
        "prompts",
        "graph",
        "parameters",
        "consistency",
        "coverage",
        "requirements",
        "status",
        "evaluation",
        "coverage_dimensions",
        "document_set",
    }
    assert r["counts"]["status"] >= 6  # every column is draft, and some are stale
    assert r["counts"]["evaluation"] == 4  # open failures in the fixture's entity table
    assert r["counts"]["coverage_dimensions"] == 1
    assert (
        r["counts"]["document_set"] == 1
        and r["by_cause"]["document_set"][0]["code"] == "DOCSET_NO_PROJECT"
    )
    assert "verdict" not in r and "ready" not in {k.lower() for k in r}


def test_readiness_scopes_consistency_and_parameters_to_the_table(harbor):
    r = table_readiness(HARBOR, "Real Estate Leases")
    assert any(f["code"] == "ENTITY_NAME_VARIANT" for f in r["by_cause"]["consistency"])
    assert not any(f["code"] == "DATE_PATTERN_DIVERGENT" for f in r["by_cause"]["consistency"])
    parameter_set(
        HARBOR,
        "Pending",
        consumers=[ConsumerBinding(table="Real Estate Leases", site="table_instructions")],
    )
    r = table_readiness(HARBOR, "Real Estate Leases")
    assert any(
        f["code"] == "PARAM_UNRESOLVED_CONSUMED" and "Pending" in f["observation"]
        for f in r["by_cause"]["parameters"]
    )


def test_readiness_clean_table_has_only_lifecycle_findings(conn):
    matter_open("M", create=True, vault_project_id="vp")
    table_ingest(
        "M",
        "T",
        [col("A", 1, CLEAN_FR, status="verified")],
        table_instructions="## Shared rules\n\n`Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`, `Unable to determine`.",
    )
    run_record(
        "M",
        "T",
        documents_ready=3,
        coverage_dimensions=[
            k
            for k in __import__(
                "prompt_graph.constants", fromlist=["COVERAGE_DIMENSION_KEYS"]
            ).COVERAGE_DIMENSION_KEYS
            if k != "grouped"
        ],
    )
    r = table_readiness("M", "T")
    assert r["total"] == 0 and r["document_set"] == "current"


def _raw_codes(res):
    """freshness.freshness_check is the module function, so its findings are Finding objects."""
    return sorted(f.code for f in res["findings"])


def _endless_page(_url, _headers):
    """A project that always has another page: larger than any request budget."""
    return {
        "files": [{"id": "f", "uploaded_at": "2026-09-01T00:00:00Z"}],
        "has_more": True,
        "next_cursor": "next",
    }


def test_enumeration_stops_at_the_request_budget():
    files, requests, complete = harvey.list_ready_files(
        "vp", fetcher=_endless_page, api_key="k", max_requests=3
    )
    assert requests == 3 and complete is False and len(files) == 3


def test_project_too_large_to_enumerate_records_no_snapshot(harbor, monkeypatch):
    """A prefix of the file list is not the document set, so nothing is written."""
    monkeypatch.setenv(harvey.ENV_KEY, "k")
    matter_open(HARBOR, vault_project_id="vp-big")
    r = freshness.freshness_check(harbor, HARBOR, refresh=True, fetcher=_endless_page)

    assert r["refreshed"] == []
    too_large = [f for f in r["findings"] if f.code == "DOCSET_TOO_LARGE_TO_ENUMERATE"]
    assert len(too_large) == 1
    assert too_large[0].evidence["requests_spent"] == harvey.MAX_REQUESTS_PER_POLL
    # No snapshot, so every table still reads as unobserved rather than as a shrunken set.
    assert all(t["state"] == "unobserved" for t in r["tables"])


def test_request_budget_is_shared_across_projects(harbor, monkeypatch):
    """Vault's limit is per organisation, so one oversized project cannot starve the rest
    silently: the projects it crowded out are reported."""
    monkeypatch.setenv(harvey.ENV_KEY, "k")
    matter_open(HARBOR, vault_project_id="vp-matter")
    table_ingest(HARBOR, ER, [], table_meta=TableMeta(vault_project_id="vp-big"))
    table_ingest(HARBOR, "Charter Documents", [], table_meta=TableMeta(vault_project_id="vp-two"))

    # Three distinct projects: vp-big, vp-two, and vp-matter for the two untouched tables.
    # The first spends the whole budget; both of the others are reported, never skipped silently.
    r = freshness.freshness_check(harbor, HARBOR, refresh=True, fetcher=_endless_page)
    assert r["refreshed"] == []
    assert _raw_codes(r).count("DOCSET_TOO_LARGE_TO_ENUMERATE") == 1
    assert _raw_codes(r).count("DOCSET_POLL_BUDGET_SPENT") == 2


def test_rate_limit_stops_the_rest_of_the_call(harbor, monkeypatch):
    """A 429 is organisation-wide, so the remaining projects are reported, not re-polled."""
    monkeypatch.setenv(harvey.ENV_KEY, "k")
    calls: list[str] = []

    def rate_limited(url, _headers):
        calls.append(url)
        raise harvey.HarveyUnavailable("rate limited", rate_limited=True)

    matter_open(HARBOR, vault_project_id="vp-matter")
    table_ingest(HARBOR, ER, [], table_meta=TableMeta(vault_project_id="vp-one"))

    r = freshness.freshness_check(harbor, HARBOR, refresh=True, fetcher=rate_limited)
    assert len(calls) == 1  # the second project is never polled
    assert _raw_codes(r).count("HARVEY_UNAVAILABLE") == 1
    assert _raw_codes(r).count("DOCSET_POLL_BUDGET_SPENT") == 1
