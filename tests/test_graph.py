"""Cross-table impact, dependency order, cycle safety, and staleness (requirements §6, §7)."""

from __future__ import annotations

from prompt_graph import graph, service
from prompt_graph.models import AdvisoryRef, ConsumerBinding
from prompt_graph.server import (
    column_revise,
    impact_of_change,
    matter_open,
    parameter_set,
    run_record,
    staleness_report,
    table_ingest,
    table_instructions_set,
)
from tests.conftest import CLEAN_CLASSIFY, CLEAN_FR, HARBOR, col


def seq(res):
    return [(s["table"], s["column"], s["impact"]) for s in res["rerun_sequence"]]


# --- impact across tables ------------------------------------------------------------------


def test_impact_crosses_tables_via_parameter_and_advisory(harbor):
    res = impact_of_change(HARBOR, table="Entity Register", column="Principal Entity")
    tables = res["tables_affected"]
    assert set(tables) == {"Charter Documents", "Real Estate Leases", "Material Contracts"}
    assert res["affected_count"] == 12
    kinds = {v["kind"] for s in res["rerun_sequence"] for v in s["via"]}
    assert "cross_table_parameter" in kinds and "advisory" in kinds and "intra_table_ref" in kinds


def test_impact_orders_within_table_by_dependency(harbor):
    res = impact_of_change(HARBOR, table="Entity Register", column="Principal Entity")
    order = [(s["table"], s["column"]) for s in res["rerun_sequence"]]
    charter = [c for t, c in order if t == "Charter Documents"]
    assert charter.index("Transfer Restrictions") < charter.index("Transfer Restriction Detail")
    contracts = [c for t, c in order if t == "Material Contracts"]
    assert (
        contracts.index("Harbor Party")
        < contracts.index("Change of Control Trigger")
        < contracts.index("Counterparty Consent Detail")
    )


def test_direct_vs_transitive(harbor):
    res = impact_of_change(HARBOR, table="Entity Register", column="Execution Status")
    assert seq(res) == [
        ("Entity Register", "Signatories", "direct"),
        ("Entity Register", "Human Review Flags", "direct"),  # also referenced directly
    ]
    res2 = impact_of_change(HARBOR, table="Charter Documents", column="Document Type")
    assert seq(res2) == [
        ("Charter Documents", "Transfer Restrictions", "direct"),
        ("Charter Documents", "Transfer Restriction Detail", "transitive"),
        ("Charter Documents", "Change of Control Consent", "direct"),
    ]


def test_impact_of_parameter_lists_consumers_and_text_sites(harbor):
    res = impact_of_change(
        HARBOR, parameter="Target Legal Name", new_value="Harbor Logistics Holdings LLC"
    )
    assert res["subject"]["new_value"] == "Harbor Logistics Holdings LLC"
    assert {c["table"] for c in res["consumers"]} == {
        "Charter Documents",
        "Real Estate Leases",
        "Material Contracts",
    }
    sites = res["text_sites_containing_current_value"]
    bound = [s for s in sites if not s.get("unbound")]
    assert {s["table"] for s in bound} == {
        "Charter Documents",
        "Real Estate Leases",
        "Material Contracts",
    }
    unbound = [s for s in sites if s.get("unbound")]
    assert [s["table"] for s in unbound] == ["Entity Register"]  # the source table mentions it too
    assert res["direct_count"] == 12 and res["transitive_count"] == 0


def test_impact_column_level_binding_is_direct_and_downstream_transitive(conn):
    matter_open("M", create=True)
    table_ingest("M", "T1", [col("Name", 1, CLEAN_FR)])
    table_ingest(
        "M", "T2", [col("Party", 1, CLEAN_FR), col("Detail", 2, "Use @Party.\n" + CLEAN_FR)]
    )
    parameter_set(
        "M",
        "Target",
        "Acme, Inc.",
        "T1",
        "Name",
        [ConsumerBinding(table="T2", column="Party", site="column_prompt")],
    )
    res = impact_of_change("M", table="T1", column="Name")
    assert seq(res) == [("T2", "Party", "direct"), ("T2", "Detail", "transitive")]
    res_p = impact_of_change("M", parameter="Target")
    assert seq(res_p) == [("T2", "Party", "direct"), ("T2", "Detail", "transitive")]


# --- cycles --------------------------------------------------------------------------------


def test_cycle_via_advisory_edges_does_not_loop(conn):
    matter_open("M", create=True)
    table_ingest("M", "T1", [col("A", 1, CLEAN_FR)])
    table_ingest(
        "M", "T2", [col("B", 1, CLEAN_FR, advisory_upstream=[AdvisoryRef(table="T1", column="A")])]
    )
    service.column_revise(
        conn, "M", "T1", "A", advisory_upstream=[AdvisoryRef(table="T2", column="B")]
    )
    res = impact_of_change("M", table="T1", column="A")
    assert [f["code"] for f in res["findings"]] == ["GRAPH_CYCLE"]
    assert [s["column"] for s in res["rerun_sequence"]] == ["B"]
    assert res["rerun_sequence"][0]["in_cycle"]
    g = graph.load_graph(conn, service.get_matter(conn, "M")["id"])
    assert len(graph.find_cycles(g)) == 1
    rep = staleness_report("M")
    assert rep["counts"]["never_run"] == 2


def test_cycle_via_forward_and_back_references(conn):
    matter_open("M", create=True)
    table_ingest(
        "M",
        "T",
        [
            col("A", 1, "Use @B.\n" + CLEAN_FR),
            col("B", 2, "Use @A.\n" + CLEAN_FR),
            col("C", 3, "Use @B.\n" + CLEAN_FR),
        ],
    )
    res = impact_of_change("M", table="T", column="A")
    cols = [s["column"] for s in res["rerun_sequence"]]
    assert set(cols) == {"B", "C"}
    assert any(f["code"] == "GRAPH_CYCLE" for f in res["findings"])
    # C is not in the cycle and is sequenced after the cyclic part is listed.
    assert [s["in_cycle"] for s in res["rerun_sequence"] if s["column"] == "C"] == [False]


def test_three_node_cycle_across_three_tables(conn):
    matter_open("M", create=True)
    table_ingest("M", "T1", [col("A", 1, CLEAN_FR)])
    table_ingest(
        "M", "T2", [col("B", 1, CLEAN_FR, advisory_upstream=[AdvisoryRef(table="T1", column="A")])]
    )
    table_ingest(
        "M", "T3", [col("C", 1, CLEAN_FR, advisory_upstream=[AdvisoryRef(table="T2", column="B")])]
    )
    service.column_revise(
        conn, "M", "T1", "A", advisory_upstream=[AdvisoryRef(table="T3", column="C")]
    )
    res = impact_of_change("M", table="T2", column="B")
    assert {s["column"] for s in res["rerun_sequence"]} == {"C", "A"}
    assert res["findings"][0]["code"] == "GRAPH_CYCLE"
    # staleness must terminate too
    run_record("M", "T1")
    column_revise("M", "T1", "A", prompt_text=CLEAN_FR + " changed")
    rep = staleness_report("M")
    assert rep["counts"]["direct"] == 1


# --- staleness -----------------------------------------------------------------------------


def _states(rep):
    return {(i["table"], i["column"]): i["state"] for i in rep["stale"]}


def test_never_run_then_current(harbor):
    rep = staleness_report(HARBOR)
    assert rep["counts"] == {"never_run": 18, "current": 0, "direct": 0, "transitive": 0}
    run_record(HARBOR, "Entity Register")
    rep = staleness_report(HARBOR, table="Entity Register")
    assert rep["counts"]["current"] == 6 and rep["stale"] == []


def test_prompt_change_marks_direct_and_downstream_transitive(harbor):
    for t in ("Entity Register", "Charter Documents", "Real Estate Leases", "Material Contracts"):
        run_record(HARBOR, t)
    column_revise(
        HARBOR, "Entity Register", "Execution Status", prompt_text=CLEAN_CLASSIFY, change_note="x"
    )
    rep = staleness_report(HARBOR)
    st = _states(rep)
    assert st[("Entity Register", "Execution Status")] == "direct"
    assert st[("Entity Register", "Signatories")] == "transitive"
    assert st[("Entity Register", "Human Review Flags")] == "transitive"
    assert ("Entity Register", "Document Type") not in st
    assert rep["rerun_order"] == [
        "Entity Register / Execution Status",
        "Entity Register / Signatories",
        "Entity Register / Human Review Flags",
    ]


def test_upstream_change_crosses_tables_transitively(harbor):
    for t in ("Entity Register", "Charter Documents", "Real Estate Leases", "Material Contracts"):
        run_record(HARBOR, t)
    column_revise(HARBOR, "Entity Register", "Principal Entity", prompt_text=CLEAN_FR)
    st = _states(staleness_report(HARBOR))
    assert st[("Entity Register", "Principal Entity")] == "direct"
    assert st[("Real Estate Leases", "Tenant Entity")] == "transitive"  # advisory edge
    assert (
        st[("Charter Documents", "Transfer Restriction Detail")] == "transitive"
    )  # via parameter fan-out
    assert ("Entity Register", "Document Type") not in st


def test_rerun_clears_staleness_in_order(harbor):
    run_record(HARBOR, "Entity Register")
    column_revise(HARBOR, "Entity Register", "Execution Status", prompt_text=CLEAN_CLASSIFY)
    run_record(HARBOR, "Entity Register", columns=["Execution Status"])
    st = _states(staleness_report(HARBOR, table="Entity Register"))
    assert ("Entity Register", "Execution Status") not in st
    assert st[("Entity Register", "Signatories")] == "transitive"  # upstream changed after its run
    run_record(HARBOR, "Entity Register", columns=["Signatories", "Human Review Flags"])
    assert staleness_report(HARBOR, table="Entity Register")["stale"] == []


def test_instructions_change_marks_whole_table_direct(harbor):
    run_record(HARBOR, "Charter Documents")
    table_instructions_set(HARBOR, "Charter Documents", "## Shared rules\n\nnew text")
    rep = staleness_report(HARBOR, table="Charter Documents")
    assert rep["counts"]["direct"] == 4
    assert all("table instructions changed" in r for i in rep["stale"] for r in i["reasons"])


def test_parameter_resolution_marks_consumers_direct(harbor):
    for t in ("Charter Documents", "Real Estate Leases", "Material Contracts"):
        run_record(HARBOR, t)
    parameter_set(HARBOR, "Target Legal Name", value="Harbor Logistics Holdings LLC")
    rep = staleness_report(HARBOR)
    assert rep["counts"]["direct"] == 12
    assert all(
        "Target Legal Name" in " ".join(i["reasons"])
        for i in rep["stale"]
        if i["state"] == "direct"
    )


def test_unchanged_parameter_value_does_not_stale(harbor):
    run_record(HARBOR, "Charter Documents")
    parameter_set(
        HARBOR, "Target Legal Name", value="Harbor Logistics Holdings, LLC", note="reconfirmed"
    )
    assert staleness_report(HARBOR, table="Charter Documents")["stale"] == []


def test_column_read_exposes_staleness(harbor):
    from prompt_graph.server import column_read

    run_record(HARBOR, "Entity Register")
    column_revise(HARBOR, "Entity Register", "Document Type", prompt_text=CLEAN_CLASSIFY)
    r = column_read(HARBOR, "Entity Register", "Formation Date")
    assert r["staleness"]["state"] == "transitive"
