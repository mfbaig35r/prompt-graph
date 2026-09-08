"""Runs, evaluation logging, open failures, summaries, and regression comparison (P2)."""

from __future__ import annotations

from prompt_graph.models import EvalRecord
from prompt_graph.server import (
    column_read,
    column_revise,
    columns_find,
    eval_record,
    failures_summary,
    matter_open,
    run_compare,
    run_record,
    table_ingest,
)
from tests.conftest import CLEAN_CLASSIFY, CLEAN_FR, HARBOR, col

ER = "Entity Register"


def ev(column, doc, passed, fc=None, answer=None, **kw):
    return EvalRecord(
        column=column,
        test_document=doc,
        passed=passed,
        failure_class=fc,
        actual_answer=answer,
        error_type=None if passed else kw.pop("error_type", "substantive"),
        **kw,
    )


def test_run_snapshot_records_versions(harbor):
    r = run_record(
        HARBOR,
        ER,
        note="first",
        coverage_dimensions=["document_types", "Silent", "grouped", "nonsense"],
    )
    assert len(r["snapshot"]) == 6 and all(s["version"] == "v1.0" for s in r["snapshot"])
    assert r["instructions_version"] == 1
    assert r["coverage_dimensions"] == ["document_types", "silent", "grouped"]
    codes = sorted(f["code"] for f in r["findings"])
    assert codes == ["COVERAGE_DIMENSION_NOT_APPLICABLE", "COVERAGE_DIMENSION_UNKNOWN"]


def test_eval_record_validates_and_defaults_version(harbor):
    run_record(HARBOR, ER)
    res = eval_record(
        HARBOR,
        ER,
        [
            ev("Execution Status", "doc1", False, "Evidence overstatement"),
            ev("Execution Status", "doc2", True),
            EvalRecord(
                column="Execution Status",
                test_document="doc3",
                passed=False,
                failure_class="made_up",
                error_type="odd",
                prompt_version="v9.9",
            ),
            EvalRecord(
                column="Execution Status",
                test_document="doc4",
                passed=True,
                failure_class="scope_leakage",
            ),
            EvalRecord(column="Execution Status", test_document="doc5", passed=False),
        ],
    )
    assert res["stored"] == 5 and res["passed"] == 2 and res["failed"] == 3
    codes = sorted(f["code"] for f in res["findings"])
    assert codes == [
        "ERROR_TYPE_INVALID",
        "FAILURE_CLASS_INVALID",
        "FAILURE_CLASS_MISSING",
        "FAILURE_FIELDS_ON_PASS",
        "PROMPT_VERSION_MISMATCH",
    ]
    stored = harbor.execute(
        "SELECT prompt_version, failure_class FROM eval_result ORDER BY id"
    ).fetchall()
    assert (
        stored[0]["prompt_version"] == "v1.0"
        and stored[0]["failure_class"] == "evidence_overstatement"
    )


def test_eval_requires_a_run(harbor):
    res = eval_record(HARBOR, ER, [ev("Execution Status", "d", True)])
    assert "Record the run first" in res["error"]


def test_open_failure_closes_on_later_pass(harbor):
    run_record(HARBOR, ER)
    eval_record(
        HARBOR,
        ER,
        [
            ev("Execution Status", "doc1", False, "scope_leakage"),
            ev("Execution Status", "doc2", False, "scope_leakage"),
        ],
    )
    assert column_read(HARBOR, ER, "Execution Status")["evaluation"]["open_failures"] == 2
    column_revise(
        HARBOR,
        ER,
        "Execution Status",
        prompt_text=CLEAN_CLASSIFY,
        failure_class_addressed="scope_leakage",
    )
    run_record(HARBOR, ER, columns=["Execution Status"])
    eval_record(HARBOR, ER, [ev("Execution Status", "doc1", True)])
    summary = column_read(HARBOR, ER, "Execution Status")["evaluation"]
    assert (
        summary["open_failures"] == 1 and summary["documents_tested"] == 2 and summary["runs"] == 2
    )
    found = columns_find(HARBOR, failure_class="scope_leakage")
    assert [c["name"] for c in found["columns"]] == ["Execution Status"]
    assert columns_find(HARBOR, failure_class="verbosity")["count"] == 0


def test_failures_summary_groups_and_recurring(harbor_evaluated):
    res = failures_summary(HARBOR)
    assert res["open_failures"] == 5
    assert [(g["key"], g["count"]) for g in res["groups"]][0] == ("scope_leakage", 2)
    assert res["groups"][0]["label"] == "Scope leakage"
    by_table = failures_summary(HARBOR, group_by="table")
    assert {g["key"]: g["count"] for g in by_table["groups"]} == {
        "Entity Register": 4,
        "Charter Documents": 1,
    }
    only = failures_summary(HARBOR, table="Charter Documents", group_by="column")
    assert [g["key"] for g in only["groups"]] == ["Change of Control Consent"]
    # make scope_leakage recurring across tables
    run_record(HARBOR, "Charter Documents")
    eval_record(HARBOR, "Charter Documents", [ev("Document Type", "x", False, "scope_leakage")])
    rec = [
        f for f in failures_summary(HARBOR)["findings"] if f["code"] == "FAILURE_CLASS_RECURRING"
    ]
    assert rec and rec[0]["evidence"]["failure_class"] == "scope_leakage"


def test_run_compare_buckets(harbor):
    run_record(HARBOR, ER, note="v1.0")
    eval_record(
        HARBOR,
        ER,
        [
            ev("Execution Status", "a", False, "scope_leakage"),
            ev("Execution Status", "b", False, "scope_leakage"),
            ev("Execution Status", "c", True),
            ev("Execution Status", "d", True),
            ev("Execution Status", "only-earlier", True),
        ],
    )
    column_revise(HARBOR, ER, "Execution Status", prompt_text=CLEAN_CLASSIFY)
    run_record(HARBOR, ER, note="v1.1", columns=["Execution Status"])
    eval_record(
        HARBOR,
        ER,
        [
            ev("Execution Status", "a", True),
            ev("Execution Status", "b", False, "scope_leakage"),
            ev("Execution Status", "c", False, "verbosity"),
            ev("Execution Status", "d", True),
            ev("Execution Status", "only-later", True),
        ],
    )
    res = run_compare(HARBOR, ER)
    assert res["totals"] == {
        "fixed": 1,
        "still_failing": 1,
        "newly_failing": 1,
        "still_passing": 1,
        "only_in_earlier": 1,
        "only_in_later": 1,
    }
    c = res["columns"][0]
    assert c["earlier_version"] == "v1.0" and c["later_version"] == "v1.1"
    assert c["fixed"][0]["document"] == "a" and c["newly_failing"][0]["document"] == "c"
    assert res["findings"][0]["code"] == "REGRESSION" and res["findings"][0]["evidence"][
        "documents"
    ] == ["c"]
    explicit = run_compare(
        HARBOR,
        ER,
        run_a=res["earlier_run"]["run_id"],
        run_b=res["later_run"]["run_id"],
        column="Execution Status",
    )
    assert explicit["totals"] == res["totals"]


def test_run_compare_needs_two_runs(harbor):
    run_record(HARBOR, ER)
    assert "fewer than two runs" in run_compare(HARBOR, ER)["error"]


def test_matter_overview_counts(harbor_evaluated):
    ov = matter_open(HARBOR)
    assert ov["created"] is False
    assert ov["open_failures"] == 5
    er = next(t for t in ov["tables"] if t["table"] == "Entity Register")
    assert er["staleness"]["direct"] == 1 and er["staleness"]["transitive"] == 2
    assert er["coverage_unticked"] == 8
    assert ov["unresolved_parameters"] == []
    assert ov["memo_outline"]["version"] == 1


def test_run_on_unknown_column_errors(conn):
    matter_open("M", create=True)
    table_ingest("M", "T", [col("A", 1, CLEAN_FR)])
    assert "Unknown columns" in run_record("M", "T", columns=["Nope"])["error"]
