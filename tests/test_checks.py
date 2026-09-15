"""suite_check families and standard contradictions (requirements §6, §8)."""

from __future__ import annotations

from prompt_graph.checks import entity_variants
from prompt_graph.models import ConsumerBinding, EntityRecord, TableMeta
from prompt_graph.server import (
    column_revise,
    matter_open,
    parameter_set,
    standard_set,
    suite_check,
    table_ingest,
    table_instructions_set,
)
from tests.conftest import CLEAN_CLASSIFY, CLEAN_FR, HARBOR, col

INSTR = "## Shared rules\n\n- Dates as `YYYY-MM-DD`.\n- `Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`, `Unable to determine`."


def by_code(res):
    out: dict[str, list] = {}
    for f in res["findings"]:
        out.setdefault(f["code"], []).append(f)
    return out


# --- demo matter ---------------------------------------------------------------------------


def test_demo_matter_findings(harbor):
    res = suite_check(HARBOR)
    b = by_code(res)
    assert res["checks_run"] == ["prompts", "graph", "parameters", "consistency"]
    assert [f["evidence"]["variant"] for f in b["ENTITY_NAME_VARIANT"]] == ["Harbor Cold Chain LLC"]
    assert b["DATE_PATTERN_DIVERGENT"][0]["evidence"]["pattern"] == "MM/DD/YYYY"
    assert b["CURRENCY_PATTERN_DIVERGENT"][0]["evidence"]["style"] == "$9,999.99"
    assert {f["evidence"]["concept"] for f in b["CONCEPT_NAME_VARIANT"]} == {
        "principal entity",
        "change of control consent",
    }
    assert "GRAPH_CYCLE" not in b and "REF_UNRESOLVED" not in b


def test_check_families_filter(harbor):
    res = suite_check(HARBOR, checks=["graph", "bogus"])
    assert res["checks_run"] == ["graph"] and res["unknown_checks"] == ["bogus"]
    assert res["findings"] == []


def test_table_filter(harbor):
    res = suite_check(HARBOR, checks=["consistency"], table="Real Estate Leases")
    b = by_code(res)
    assert "ENTITY_NAME_VARIANT" in b
    assert "DATE_PATTERN_DIVERGENT" not in b  # that one is in Material Contracts


# --- graph family --------------------------------------------------------------------------


def test_graph_cycle_reported(conn):
    matter_open("M", create=True)
    table_ingest(
        "M",
        "T",
        [col("A", 1, "Use @B.\n" + CLEAN_FR), col("B", 2, "Use @A.\n" + CLEAN_FR)],
        table_instructions=INSTR,
    )
    b = by_code(suite_check("M", checks=["graph"]))
    assert (
        len(b["GRAPH_CYCLE"]) == 1
        and b["GRAPH_CYCLE"][0]["evidence"]["cycle"][0]
        == b["GRAPH_CYCLE"][0]["evidence"]["cycle"][-1]
    )
    assert b["REF_FORWARD"][0]["subject_name"] == "A"


def test_role_order_violation(conn):
    matter_open("M", create=True)
    table_ingest(
        "M",
        "T",
        [
            col("Detail", 1, CLEAN_FR, role="extraction"),
            col(
                "Type", 2, "Use @Detail.\n" + CLEAN_CLASSIFY, "Classify", ["A"], role="orientation"
            ),
        ],
        table_instructions=INSTR,
    )
    b = by_code(suite_check("M", checks=["graph"]))
    assert b["ROLE_ORDER_VIOLATION"][0]["subject_name"] == "Type"


def test_control_plane_narrative(conn):
    matter_open("M", create=True)
    table_ingest(
        "M",
        "T",
        [
            col("Summary", 1, CLEAN_FR),
            col("X", 2, "Use @Summary.\n" + CLEAN_FR),
            col("Y", 3, "Use @Summary.\n" + CLEAN_FR),
        ],
        table_instructions=INSTR,
    )
    b = by_code(suite_check("M", checks=["graph"]))
    assert b["CONTROL_PLANE_NARRATIVE"][0]["evidence"]["dependents"] == ["X", "Y"]


def test_control_plane_not_flagged_for_classify(conn):
    matter_open("M", create=True)
    table_ingest(
        "M",
        "T",
        [
            col("Status", 1, CLEAN_CLASSIFY, "Classify", ["A"]),
            col("X", 2, "Use @Status.\n" + CLEAN_FR),
            col("Y", 3, "Use @Status.\n" + CLEAN_FR),
        ],
        table_instructions=INSTR,
    )
    assert "CONTROL_PLANE_NARRATIVE" not in by_code(suite_check("M", checks=["graph"]))


def test_dependency_on_retired(conn):
    matter_open("M", create=True)
    table_ingest(
        "M",
        "T",
        [col("A", 1, CLEAN_FR), col("B", 2, "Use @A.\n" + CLEAN_FR)],
        table_instructions=INSTR,
    )
    column_revise("M", "T", "A", status="retired")
    assert (
        by_code(suite_check("M", checks=["graph"]))["DEPENDENCY_ON_RETIRED"][0]["subject_name"]
        == "B"
    )


# --- parameters family ---------------------------------------------------------------------


def test_orphaned_and_unresolved_parameters(conn):
    matter_open("M", create=True)
    table_ingest("M", "T", [col("A", 1, CLEAN_FR)], table_instructions=INSTR)
    parameter_set("M", "Orphan", "x")
    parameter_set("M", "Pending", consumers=[ConsumerBinding(table="T", site="table_instructions")])
    b = by_code(suite_check("M", checks=["parameters"]))
    assert b["PARAM_ORPHANED"][0]["subject_name"] == "Orphan"
    assert b["PARAM_UNRESOLVED_CONSUMED"][0]["subject_name"] == "Pending"


def test_parameter_not_bound_to_instructions_and_value_absent(conn):
    matter_open("M", create=True)
    table_ingest("M", "T", [col("A", 1, CLEAN_FR)], table_instructions=INSTR)
    parameter_set(
        "M",
        "Target",
        "Acme, Inc.",
        consumers=[ConsumerBinding(table="T", column="A", site="column_prompt")],
    )
    b = by_code(suite_check("M", checks=["parameters"]))
    assert "PARAM_NOT_BOUND_TO_INSTRUCTIONS" in b
    assert b["PARAM_VALUE_ABSENT_FROM_PROMPT"][0]["subject_name"] == "A"
    parameter_set("M", "Target", consumers=[ConsumerBinding(table="T", site="table_instructions")])
    b = by_code(suite_check("M", checks=["parameters"]))
    assert "PARAM_NOT_BOUND_TO_INSTRUCTIONS" not in b
    assert "PARAM_VALUE_ABSENT_FROM_INSTRUCTIONS" in b
    table_instructions_set("M", "T", INSTR + "\n- Target: Acme, Inc.")
    assert "PARAM_VALUE_ABSENT_FROM_INSTRUCTIONS" not in by_code(
        suite_check("M", checks=["parameters"])
    )


def test_dangling_binding_and_retired_source(conn):
    matter_open("M", create=True)
    table_ingest("M", "T1", [col("Src", 1, CLEAN_FR)], table_instructions=INSTR)
    table_ingest(
        "M",
        "T2",
        [col("Dst", 1, "Acme, Inc.\n" + CLEAN_FR)],
        table_instructions=INSTR + "\nAcme, Inc.",
    )
    parameter_set(
        "M",
        "P",
        "Acme, Inc.",
        "T1",
        "Src",
        [
            ConsumerBinding(table="T2", column="Dst", site="column_prompt"),
            ConsumerBinding(table="T2", site="table_instructions"),
        ],
    )
    column_revise("M", "T2", "Dst", status="retired")
    column_revise("M", "T1", "Src", status="retired")
    b = by_code(suite_check("M", checks=["parameters"]))
    assert "BINDING_DANGLING" in b and "PARAM_SOURCE_RETIRED" in b


# --- consistency family ----------------------------------------------------------------------


def test_entity_variants_helper():
    assert entity_variants(
        "Harbor Cold Chain LLC and Harbor Cold Chain, L.L.C.", "Harbor Cold Chain, LLC"
    ) == ["Harbor Cold Chain LLC", "Harbor Cold Chain, L.L.C."]
    assert entity_variants("Harbor Cold Chain, LLC", "Harbor Cold Chain, LLC") == []
    assert entity_variants("Harbor Cold Chain", "Harbor Cold Chain, LLC") == ["Harbor Cold Chain"]


def test_instructions_missing_and_vocabulary_incomplete(conn):
    matter_open("M", create=True)
    table_ingest("M", "T1", [col("A", 1, CLEAN_FR)])
    table_ingest(
        "M",
        "T2",
        [col("A", 1, CLEAN_FR)],
        table_instructions="## Shared rules\n\n`Not addressed` only.",
    )
    b = by_code(suite_check("M", checks=["consistency"]))
    assert b["INSTRUCTIONS_MISSING"][0]["subject_name"] == "T1"
    assert b["INSTRUCTIONS_VOCABULARY_INCOMPLETE"][0]["subject_name"] == "T2"
    assert set(b["INSTRUCTIONS_VOCABULARY_INCOMPLETE"][0]["evidence"]["missing"]) == {
        "Not stated",
        "Not applicable",
        "Incorporated terms",
        "Unable to determine",
    }


def test_same_name_divergent_rules_across_tables(conn):
    matter_open("M", create=True)
    table_ingest(
        "M",
        "T1",
        [col("Execution Status", 1, CLEAN_CLASSIFY, "Classify", ["Signed", "Unsigned"])],
        table_instructions=INSTR,
    )
    table_ingest(
        "M",
        "T2",
        [col("Execution Status", 1, CLEAN_CLASSIFY, "Classify", ["Executed", "Unsigned"])],
        table_instructions=INSTR,
    )
    b = by_code(suite_check("M", checks=["consistency"]))
    assert (
        len(b["CONCEPT_DIVERGENT_RULES"]) == 1
        and len(b["CONCEPT_DIVERGENT_RULES"][0]["evidence"]["option_sets"]) == 2
    )


def test_similar_names_heuristic(conn):
    matter_open("M", create=True)
    table_ingest("M", "T1", [col("Formation Date", 1, CLEAN_FR, "Date")], table_instructions=INSTR)
    table_ingest(
        "M", "T2", [col("Entity Formation Date", 1, CLEAN_FR, "Date")], table_instructions=INSTR
    )
    b = by_code(suite_check("M", checks=["consistency"]))
    assert b["CONCEPT_NAME_VARIANT"][0]["evidence"]["heuristic"] == "token overlap"


def test_date_pattern_without_standard_flags_multiple(conn):
    matter_open("M", create=True)
    standard_set("firm", date_pattern="")  # clear the seeded pattern
    table_ingest(
        "M", "T1", [col("A", 1, "`YYYY-MM-DD`\n" + CLEAN_FR, "Date")], table_instructions=INSTR
    )
    table_ingest(
        "M", "T2", [col("A", 1, "`DD/MM/YYYY`\n" + CLEAN_FR, "Date")], table_instructions=INSTR
    )
    b = by_code(suite_check("M", checks=["consistency"]))
    assert "no standard pattern" in b["DATE_PATTERN_DIVERGENT"][0]["observation"]


# --- standard ------------------------------------------------------------------------------


def test_matter_standard_cannot_contradict_firm(harbor):
    res = standard_set(
        "matter",
        HARBOR,
        date_pattern="DD/MM/YYYY",
        entities=[EntityRecord(name="Harbor Logistics Holdings, LLC")],
    )
    codes = [f["code"] for f in res["findings"]]
    assert codes == ["STANDARD_CONTRADICTS_FIRM"]
    assert res["effective"]["date_pattern"] == "YYYY-MM-DD"
    assert res["effective"]["overridden_by_firm"] == ["date_pattern"]
    assert res["effective"]["entities"][0]["name"] == "Harbor Logistics Holdings, LLC"
    assert res["version"] == 2  # the seed created version 1


def test_firm_vocabulary_change_is_reported(conn):
    res = standard_set("firm", fallback_vocabulary=["Not addressed", "N/A"])
    assert [f["code"] for f in res["findings"]] == ["STANDARD_VOCABULARY_NOT_SKILL"]


def test_standard_fields_carry_forward(conn):
    standard_set("firm", currency_pattern="USD 1,000.00")
    res = standard_set("firm", naming_rules="exact names")
    assert res["effective"]["currency_pattern"] == "USD 1,000.00" and res["version"] == 3


# --- name-variant clustering and confidence --------------------------------------------------


def _seed(rows):
    """rows: (table, column, role). One column per table, enough to compare names across."""
    matter_open(HARBOR, create=True)
    for table, column, role in rows:
        table_ingest(
            HARBOR,
            table,
            [col(column, 1, CLEAN_FR, role=role)],
            table_meta=TableMeta(review_unit="one document"),
            table_instructions=INSTR,
        )
    return by_code(suite_check(HARBOR)).get("CONCEPT_NAME_VARIANT", [])


def test_one_finding_per_cluster_not_per_module_pair(conn):
    """One finding was emitted per column PAIR, so a name used in n tables produced n-1
    identical findings about the same concept."""
    v = _seed(
        [(f"T{i}", "Documents in Unit", "orientation") for i in range(1, 6)]
        + [("TX", "Governing Documents in Unit", "orientation")]
    )
    assert len(v) == 1, [f["observation"] for f in v]
    e = v[0]["evidence"]
    assert set(e["names"]) == {"Documents in Unit", "Governing Documents in Unit"}
    assert len(e["columns"]) == 6  # every instance still listed, nothing lost by grouping


def test_unrelated_provisions_sharing_a_preposition_do_not_cluster(conn):
    """`on`, `change` and `control` are shared by provisions with nothing else in common;
    counting prepositions as meaning merged them at exactly the 0.6 threshold."""
    assert (
        _seed(
            [
                ("A", "Acceleration on Change of Control", "extraction"),
                ("B", "Survival on Change of Control", "extraction"),
                ("C", "Transferability on Change of Control", "extraction"),
            ]
        )
        == []
    )


def test_qualifier_downgrades_confidence(conn):
    """A plan's default and one instrument's actual are different questions."""
    (f,) = _seed(
        [
            ("A", "Post-Termination Exercise Period", "extraction"),
            ("B", "Default Post-Termination Exercise", "extraction"),
        ]
    )
    assert f["evidence"]["confidence"] == "possible"
    assert any("qualifier" in r for r in f["evidence"]["confidence_reasons"])


def test_substantive_role_drift_does_not_downgrade(conn):
    """Extraction, validation and reconciliation routinely drift on one question. Counting that
    as evidence of difference downgraded the strongest real finding in the corpus."""
    (f,) = _seed(
        [
            ("A", "Owner Matches Target Entity", "extraction"),
            ("B", "Holder Matches Target Entity", "reconciliation"),
        ]
    )
    assert f["evidence"]["confidence"] == "strong", f["evidence"]["confidence_reasons"]


def test_orientation_boundary_does_downgrade(conn):
    """Orientation runs first and establishes the row, so orientation versus substantive is a
    real signal that two questions differ."""
    (f,) = _seed(
        [
            ("A", "Dispute Resolution", "orientation"),
            ("B", "Dispute Resolution Provisions", "extraction"),
        ]
    )
    assert f["evidence"]["confidence"] == "possible"
    assert any("orientation" in r for r in f["evidence"]["confidence_reasons"])


def test_transitive_membership_is_flagged(conn):
    """A resembles B and A resembles C, but B and C do not resemble each other."""
    (f,) = _seed(
        [
            ("A", "Commencement Date", "extraction"),
            ("B", "Rent Commencement Date", "extraction"),
            ("C", "Vesting Commencement Date", "extraction"),
        ]
    )
    assert len(f["evidence"]["names"]) == 3
    assert f["evidence"]["confidence"] == "possible"
    assert any("transitively" in r for r in f["evidence"]["confidence_reasons"])
