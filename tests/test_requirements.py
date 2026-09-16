"""The requirement register: the external specification a suite is built to satisfy."""

from __future__ import annotations

import pytest

from prompt_graph.models import AssertionRecord, SectionRecord, TableMeta
from prompt_graph.server import (
    RequirementItem,
    RequirementPart,
    matter_open,
    memo_outline_set,
    requirement_set,
    requirements_ingest,
    suite_check,
    table_ingest,
)
from tests.conftest import CLEAN_FR, HARBOR, col

SRC = "Test Playbook"


def by_code(res):
    out: dict[str, list] = {}
    for f in res["findings"]:
        out.setdefault(f["code"], []).append(f)
    return out


@pytest.fixture()
def suite(conn):
    matter_open(HARBOR, create=True)
    for t in ("Contracts", "Corporate"):
        table_ingest(
            HARBOR, t, [col("A", 1, CLEAN_FR)], table_meta=TableMeta(review_unit="one doc")
        )
    memo_outline_set(
        HARBOR,
        [
            SectionRecord(
                name="IV.B Contracts",
                assertions=[AssertionRecord(text="State the governing law", kind="extraction")],
            )
        ],
        name="Memo",
    )
    return conn


def _ingest(items):
    """Pydantic coerces the nested part and link dicts on construction."""
    return requirements_ingest(
        HARBOR, source=SRC, items=[RequirementItem(**i) for i in items], citation="103pp PDF"
    )


def test_external_requirements_are_recorded_with_their_reason(suite):
    """The negative result is the point: a requirement no review table can serve, and why."""
    _ingest(
        [
            {
                "ref": "3.3.3",
                "title": "Identify Gaps Against a DDR List",
                "parts": [
                    {
                        "disposition": "external",
                        "reason": "Requires the buyer's request list; nothing in the vault says what is absent.",
                    }
                ],
            }
        ]
    )
    (f,) = by_code(suite_check(HARBOR, checks=["requirements"]))["REQUIREMENT_EXTERNAL"]
    assert "buyer's request list" in f["observation"]


def test_a_requirement_can_split_into_parts_with_different_answers(suite):
    """3.4.7 is 'Part A needs the checklist, Part B becomes memo section IV.B'."""
    _ingest(
        [
            {
                "ref": "3.4.7",
                "title": "Flag Missing Contracts and Synthesize Findings",
                "parts": [
                    {
                        "label": "Part A",
                        "disposition": "external",
                        "reason": "Needs the checklist.",
                    },
                    {
                        "label": "Part B",
                        "disposition": "synthesis",
                        "links": [
                            {"kind": "consumes", "table": "Contracts"},
                            {"kind": "produces", "section": "IV.B Contracts"},
                        ],
                    },
                ],
            }
        ]
    )
    b = by_code(suite_check(HARBOR, checks=["requirements"]))
    assert [f["subject_name"] for f in b["REQUIREMENT_EXTERNAL"]] == ["3.4.7 Part A"]
    assert "REQUIREMENT_SERVED_BY_NOTHING" not in b


def test_served_without_a_table_is_reported(suite):
    _ingest([{"ref": "3.2", "title": "NDA Review", "parts": [{"disposition": "served"}]}])
    b = by_code(suite_check(HARBOR, checks=["requirements"]))
    assert len(b["REQUIREMENT_SERVED_BY_NOTHING"]) == 1


def test_a_link_to_a_table_that_does_not_exist_is_refused_and_reported(suite):
    res = _ingest(
        [
            {
                "ref": "3.4.6",
                "title": "Contracts Portfolio Risks",
                "parts": [
                    {"disposition": "synthesis", "links": [{"kind": "consumes", "table": "Nope"}]}
                ],
            }
        ]
    )
    assert [f["code"] for f in res["findings"]] == ["REQUIREMENT_TABLE_MISSING"]


def test_a_section_the_outline_does_not_have_is_refused_and_reported(suite):
    res = _ingest(
        [
            {
                "ref": "3.5.1",
                "title": "Compile the Memo",
                "parts": [
                    {
                        "disposition": "synthesis",
                        "links": [{"kind": "produces", "section": "XI. Nope"}],
                    }
                ],
            }
        ]
    )
    assert [f["code"] for f in res["findings"]] == ["REQUIREMENT_SECTION_MISSING"]


def test_tables_answering_no_requirement_are_reported(suite):
    _ingest(
        [
            {
                "ref": "3.4.5",
                "title": "Summarize a Material Contract",
                "parts": [
                    {
                        "disposition": "served",
                        "links": [{"kind": "served_by", "table": "Contracts"}],
                    }
                ],
            }
        ]
    )
    b = by_code(suite_check(HARBOR, checks=["requirements"]))
    assert [f["subject_name"] for f in b["TABLE_ANSWERS_NO_REQUIREMENT"]] == ["Corporate"]


def test_a_suite_with_no_source_says_so(suite):
    b = by_code(suite_check(HARBOR, checks=["requirements"]))
    assert list(b) == ["REQUIREMENT_SOURCE_MISSING"]


def test_re_ingesting_matches_on_ref_and_replaces_parts(suite):
    _ingest([{"ref": "3.1", "title": "Deal Structuring", "parts": [{"disposition": "unassessed"}]}])
    assert "REQUIREMENT_UNASSESSED" in by_code(suite_check(HARBOR, checks=["requirements"]))
    res = _ingest(
        [
            {
                "ref": "3.1",
                "title": "Deal Structuring",
                "parts": [{"disposition": "external", "reason": "Deal file."}],
            }
        ]
    )
    assert res["created"] == [] and res["updated"] == ["3.1"]
    b = by_code(suite_check(HARBOR, checks=["requirements"]))
    assert "REQUIREMENT_UNASSESSED" not in b and "REQUIREMENT_EXTERNAL" in b


def test_requirement_set_revises_one_requirement(suite):
    _ingest([{"ref": "3.1", "title": "Deal Structuring", "parts": [{"disposition": "unassessed"}]}])
    requirement_set(
        HARBOR, ref="3.1", parts=[RequirementPart(disposition="external", reason="Deal file.")]
    )
    b = by_code(suite_check(HARBOR, checks=["requirements"]))
    assert "REQUIREMENT_EXTERNAL" in b and "REQUIREMENT_UNASSESSED" not in b
