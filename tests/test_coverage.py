"""Memo coverage: extraction gaps vs judgment boundaries, unsourced columns, reliability (§9)."""

from __future__ import annotations

from prompt_graph.constants import COVERAGE_DIMENSION_KEYS
from prompt_graph.models import AssertionRecord, EvalRecord, SectionRecord, SourceRef
from prompt_graph.server import (
    column_revise,
    coverage_check,
    eval_record,
    matter_open,
    memo_outline_set,
    run_record,
    table_ingest,
)
from tests.conftest import CLEAN_CLASSIFY, CLEAN_FR, HARBOR, col


def statuses(res):
    return {a["assertion"]: a["status"] for s in res["sections"] for a in s["assertions"]}


def test_gap_and_boundary_are_distinct(harbor):
    res = coverage_check(HARBOR)
    st = statuses(res)
    assert st["Preemptive rights on new issuances"] == "extraction_gap"
    assert st["Pending or threatened litigation disclosed in the data room"] == "extraction_gap"
    assert st["Materiality of any identified claim to the transaction"] == "judgment_boundary"
    assert (
        st["Whether the proposed transaction triggers each identified provision"]
        == "judgment_boundary"
    )
    assert res["totals"] == {
        "assertions": 11,
        "reliably_covered": 0,
        "nominally_covered": 6,
        "extraction_gap": 2,
        "judgment_boundary": 3,
    }
    codes = {f["code"] for f in res["findings"]}
    assert {
        "COV_EXTRACTION_GAP",
        "COV_JUDGMENT_BOUNDARY",
        "COV_NOMINAL_ONLY",
        "COV_UNSOURCED_COLUMN",
    } <= codes
    gap = [f for f in res["findings"] if f["code"] == "COV_EXTRACTION_GAP"]
    assert len(gap) == 2
    jb = [f for f in res["findings"] if f["code"] == "COV_JUDGMENT_BOUNDARY"]
    assert len(jb) == 3
    with_inputs = next(f for f in jb if "operative" in f["subject_name"])
    assert with_inputs["evidence"]["evidence_inputs"] == [
        "Entity Register / Document Type",
        "Charter Documents / Document Type",
    ]


def test_judgment_assertion_is_never_a_gap_even_without_sources(harbor):
    res = coverage_check(HARBOR)
    st = statuses(res)
    assert st["Materiality of any identified claim to the transaction"] == "judgment_boundary"
    assert not any(
        f["code"] == "COV_EXTRACTION_GAP" and "Materiality" in f["subject_name"]
        for f in res["findings"]
    )


def test_unsourced_columns_listed(harbor):
    res = coverage_check(HARBOR)
    names = {(u["table"], u["column"]) for u in res["unsourced_columns"]}
    assert ("Entity Register", "Execution Status") in names
    assert ("Real Estate Leases", "Annual Base Rent") in names
    assert ("Charter Documents", "Change of Control Consent") not in names


def test_reliability_needs_run_no_failures_not_stale_all_dimensions(harbor):
    def status_of(text):
        return statuses(coverage_check(HARBOR))[text]

    key = "Leases requiring landlord consent on a change of control of the tenant"
    assert status_of(key) == "nominally_covered"  # no run
    dims = [k for k in COVERAGE_DIMENSION_KEYS if k != "grouped"]
    run_record(HARBOR, "Real Estate Leases", coverage_dimensions=dims[:-1])
    assert status_of(key) == "nominally_covered"  # one dimension unticked
    run_record(HARBOR, "Real Estate Leases", coverage_dimensions=dims)
    assert status_of(key) == "reliably_covered"
    eval_record(
        HARBOR,
        "Real Estate Leases",
        [
            EvalRecord(
                column="Assignment Consent",
                test_document="L1",
                passed=False,
                failure_class="silence_uncertainty_error",
            )
        ],
    )
    assert status_of(key) == "nominally_covered"  # open failure
    run_record(
        HARBOR, "Real Estate Leases", coverage_dimensions=dims, columns=["Assignment Consent"]
    )
    eval_record(
        HARBOR,
        "Real Estate Leases",
        [EvalRecord(column="Assignment Consent", test_document="L1", passed=True)],
    )
    assert status_of(key) == "reliably_covered"
    column_revise(HARBOR, "Real Estate Leases", "Assignment Consent", prompt_text=CLEAN_CLASSIFY)
    res = coverage_check(HARBOR)
    assert statuses(res)[key] == "nominally_covered"  # stale
    nominal = [
        f
        for f in res["findings"]
        if f["code"] == "COV_NOMINAL_ONLY" and key[:80] in f["subject_name"]
    ]
    assert nominal and "Assignment Consent (directly stale" in nominal[0]["observation"]


def test_one_reliable_source_is_enough(harbor):
    key = "Transfer restrictions on existing equity and who holds them"
    dims = [k for k in COVERAGE_DIMENSION_KEYS if k != "grouped"]
    run_record(HARBOR, "Charter Documents", coverage_dimensions=dims)
    eval_record(
        HARBOR,
        "Charter Documents",
        [
            EvalRecord(
                column="Transfer Restriction Detail",
                test_document="d",
                passed=False,
                failure_class="verbosity",
            )
        ],
    )
    res = coverage_check(HARBOR)
    a = next(a for s in res["sections"] for a in s["assertions"] if a["assertion"] == key)
    assert a["status"] == "reliably_covered"
    assert [x["reliable"] for x in a["sources"]] == [True, False]


def test_retired_source_reported(harbor):
    column_revise(HARBOR, "Charter Documents", "Change of Control Consent", status="retired")
    res = coverage_check(HARBOR)
    assert (
        statuses(res)["Charter-level consents required on a change of control"] == "extraction_gap"
    )
    assert any(f["code"] == "COV_SOURCE_RETIRED" for f in res["findings"])


def test_outline_versioning_and_unresolved_sources(conn):
    matter_open("M", create=True)
    table_ingest("M", "T", [col("A", 1, CLEAN_FR)])
    r1 = memo_outline_set(
        "M",
        [
            SectionRecord(
                name="S",
                assertions=[
                    AssertionRecord(
                        text="x",
                        kind="extraction",
                        sources=[
                            SourceRef(table="T", column="A"),
                            SourceRef(table="T", column="Missing"),
                        ],
                    )
                ],
            )
        ],
    )
    assert r1["version"] == 1 and r1["sources"] == 1
    assert [f["code"] for f in r1["findings"]] == ["COV_SOURCE_UNRESOLVED"]
    r2 = memo_outline_set(
        "M", [SectionRecord(name="S", assertions=[AssertionRecord(text="y", kind="judgment")])]
    )
    assert r2["version"] == 2
    res = coverage_check("M")
    assert res["outline_version"] == 2 and list(statuses(res)) == ["y"]


def test_invalid_kind_rejected(conn):
    matter_open("M", create=True)
    res = memo_outline_set(
        "M", [SectionRecord(name="S", assertions=[AssertionRecord(text="x", kind="maybe")])]
    )
    assert "must be 'extraction' or 'judgment'" in res["error"]


def test_coverage_without_outline_errors(conn):
    matter_open("M", create=True)
    assert "No memo outline" in coverage_check("M")["error"]
