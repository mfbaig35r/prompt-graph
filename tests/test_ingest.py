"""Ingest idempotency, versioning, explicit rename, and record validation (requirements §5)."""

from __future__ import annotations

from prompt_graph import service
from prompt_graph.models import ColumnRecord, TableMeta
from prompt_graph.server import column_read, column_revise, columns_find, matter_open, table_ingest
from tests.conftest import CLEAN_CLASSIFY, CLEAN_FR, col

M = "Test Matter"


def _codes(res):
    return sorted(f["code"] if isinstance(f, dict) else f.code for f in res["findings"])


def _ingest(conn, cols, **kw):
    return table_ingest(M, "Entities", cols, **kw)


def test_ingest_assigns_v1_and_resolves_refs(conn):
    matter_open(M, create=True)
    res = _ingest(
        conn,
        [
            col("Document Type", 1, CLEAN_CLASSIFY, "Classify", ["A", "B"]),
            col("Detail", 2, "## Established results\n\n- Type: @Document Type\n\n" + CLEAN_FR),
        ],
        table_instructions="## Shared rules\n\n`Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`, `Unable to determine`.",
    )
    assert res["created"] == ["Document Type", "Detail"]
    assert res["table_instructions"]["version"] == 1
    assert "REF_UNRESOLVED" not in _codes(res)
    d = column_read(M, "Entities", "Detail")
    assert d["version"] == "v1.0"
    assert d["upstream"] == [
        {
            "table": "Entities",
            "column": "Document Type",
            "kind": "intra_table_ref",
            "status": "draft",
            "note": None,
        }
    ]


def test_reingest_unchanged_creates_no_versions(conn):
    matter_open(M, create=True)
    cols = [col("A", 1, CLEAN_FR), col("B", 2, CLEAN_FR)]
    _ingest(conn, cols)
    res = _ingest(conn, cols)
    assert (
        res["created"] == []
        and res["new_versions"] == []
        and sorted(res["unchanged"]) == ["A", "B"]
    )
    assert res["column_count"] == 2
    assert conn.execute("SELECT COUNT(*) FROM prompt_version").fetchone()[0] == 2


def test_reingest_changed_text_versions_not_duplicates(conn):
    matter_open(M, create=True)
    _ingest(conn, [col("A", 1, CLEAN_FR), col("B", 2, CLEAN_FR)])
    res = _ingest(
        conn, [col("A", 1, CLEAN_FR + "\nExtra rule."), col("B", 2, CLEAN_FR)], source_type="excel"
    )
    assert res["new_versions"] == [{"column": "A", "version": "v1.1", "previous": "v1.0"}]
    assert res["unchanged"] == ["B"]
    assert conn.execute("SELECT COUNT(*) FROM column_def").fetchone()[0] == 2
    a = column_read(M, "Entities", "A", include_history=True)
    assert [h["version"] for h in a["history"]] == ["v1.0", "v1.1"]
    assert a["history"][-1]["is_current"] and not a["history"][0]["is_current"]
    assert "Re-ingested from excel" in a["history"][-1]["change_note"]


def test_reingest_reports_absent_columns_without_retiring(conn):
    matter_open(M, create=True)
    _ingest(conn, [col("A", 1, CLEAN_FR), col("B", 2, CLEAN_FR)])
    res = _ingest(conn, [col("A", 1, CLEAN_FR)])
    absent = [f for f in res["findings"] if f["code"] == "COLUMN_ABSENT_FROM_INGEST"]
    assert [f["subject_name"] for f in absent] == ["B"]
    assert column_read(M, "Entities", "B")["status"] == "draft"


def test_rename_is_explicit_and_reports_stale_references(conn):
    matter_open(M, create=True)
    _ingest(
        conn,
        [
            col("Doc Type", 1, CLEAN_CLASSIFY, "Classify", ["A"]),
            col("Detail", 2, "Use @Doc Type.\n" + CLEAN_FR),
        ],
    )
    # A re-ingest under a new name is a NEW column, not a rename.
    res = _ingest(
        conn,
        [
            col("Document Type", 1, CLEAN_CLASSIFY, "Classify", ["A"]),
            col("Detail", 2, "Use @Doc Type.\n" + CLEAN_FR),
        ],
    )
    assert res["created"] == ["Document Type"]
    assert "COLUMN_ABSENT_FROM_INGEST" in _codes(res)
    # The explicit rename keeps history and reports the prompt still using the old name.
    r = column_revise(M, "Entities", "Doc Type", rename_to="Doc Kind")
    assert r["changes"]["renamed_from"] == "Doc Type"
    unresolved = [f for f in r["findings"] if f["code"] == "REF_UNRESOLVED"]
    assert unresolved and unresolved[0]["subject_name"] == "Detail"
    assert column_read(M, "Entities", "Doc Kind")["version"] == "v1.0"


def test_missing_native_type_is_skipped_and_reported(conn):
    matter_open(M, create=True)
    res = _ingest(
        conn, [ColumnRecord(name="X", position=1, prompt_text=CLEAN_FR), col("Y", 2, CLEAN_FR)]
    )
    assert res["skipped"] == ["X"] and res["created"] == ["Y"]
    assert "NATIVE_TYPE_MISSING" in _codes(res)


def test_native_type_aliases_normalise(conn):
    matter_open(M, create=True)
    res = _ingest(
        conn,
        [
            col("X", 1, CLEAN_FR, "free response"),
            col("Y", 2, CLEAN_CLASSIFY, "classification", ["A"]),
        ],
    )
    assert res["created"] == ["X", "Y"]
    assert column_read(M, "Entities", "X")["native_type"] == "FreeResponse"
    assert column_read(M, "Entities", "Y")["native_type"] == "Classify"


def test_invalid_native_type_reported(conn):
    matter_open(M, create=True)
    res = _ingest(conn, [col("X", 1, CLEAN_FR, "Boolean")])
    assert res["skipped"] == ["X"] and "NATIVE_TYPE_INVALID" in _codes(res)


def test_classify_without_options_and_options_on_wrong_type(conn):
    matter_open(M, create=True)
    res = _ingest(
        conn, [col("X", 1, CLEAN_CLASSIFY, "Classify"), col("Y", 2, CLEAN_FR, "Date", ["A"])]
    )
    c = _codes(res)
    assert "OPTIONS_MISSING" in c and "OPTIONS_ON_NON_CLASSIFY" in c
    assert res["created"] == ["X", "Y"]  # stored; the finding is informational


def test_malformed_options_and_duplicate_positions(conn):
    matter_open(M, create=True)
    res = _ingest(
        conn, [col("X", 1, CLEAN_CLASSIFY, "Classify", ["A", "a", ""]), col("Y", 1, CLEAN_FR)]
    )
    c = _codes(res)
    assert "OPTIONS_MALFORMED" in c and "POSITION_DUPLICATE" in c


def test_unresolved_reference_reported_on_ingest(conn):
    matter_open(M, create=True)
    res = _ingest(conn, [col("X", 1, "Use @Nothing Here.\n" + CLEAN_FR)])
    fs = [f for f in res["findings"] if f["code"] == "REF_UNRESOLVED"]
    assert fs and fs[0]["evidence"]["reference"] == "Nothing Here"


def test_declared_upstream_refs_resolve_when_text_lacks_them(conn):
    matter_open(M, create=True)
    _ingest(
        conn,
        [
            col("Type", 1, CLEAN_CLASSIFY, "Classify", ["A"]),
            col("Detail", 2, CLEAN_FR, upstream_refs=["@Type"]),
        ],
    )
    assert column_read(M, "Entities", "Detail")["upstream"][0]["column"] == "Type"


def test_column_revise_versions_and_status(conn):
    matter_open(M, create=True)
    _ingest(conn, [col("A", 1, CLEAN_FR)])
    r = column_revise(
        M,
        "Entities",
        "A",
        prompt_text=CLEAN_FR + "\nMore.",
        change_note="tightened",
        failure_class_addressed="Scope leakage",
    )
    assert r["changes"]["version"] == "v1.1"
    r2 = column_revise(M, "Entities", "A", prompt_text=CLEAN_FR + "\nMore.", status="verified")
    assert r2["changes"].get("text_unchanged") and r2["changes"]["status"] == "verified"
    r3 = column_revise(
        M, "Entities", "A", prompt_text="## Output format\n\nRedesign.", bump="major"
    )
    assert r3["changes"]["version"] == "v2.0"
    hist = column_read(M, "Entities", "A", include_history=True)["history"]
    assert [h["version"] for h in hist] == ["v1.0", "v1.1", "v2.0"]
    assert hist[1]["failure_class_addressed"] == "scope_leakage"


def test_retire_reports_dependents(conn):
    matter_open(M, create=True)
    _ingest(
        conn,
        [
            col("Type", 1, CLEAN_CLASSIFY, "Classify", ["A"]),
            col("Detail", 2, "Use @Type.\n" + CLEAN_FR),
        ],
    )
    r = column_revise(M, "Entities", "Type", status="retired")
    dep = [f for f in r["findings"] if f["code"] == "DEPENDENCY_ON_RETIRED"]
    assert dep and dep[0]["evidence"]["dependent_column"] == "Detail"
    assert columns_find(M)["count"] == 1  # retired columns hidden by default


def test_table_meta_and_provenance(conn):
    matter_open(M, create=True)
    _ingest(
        conn,
        [col("A", 1, CLEAN_FR)],
        table_meta=TableMeta(review_unit="one lease", grouping_enabled=True, max_docs_per_unit=25),
        source_type="harvey_export",
        actor="paralegal",
    )
    t = service.get_table(conn, service.get_matter(conn, M)["id"], "Entities")
    assert t["review_unit"] == "one lease" and t["grouping_enabled"] == 1
    log = column_read(M, "Entities", "A", include_history=True)["change_log"]
    assert log[0]["source"] == "harvey_export" and log[0]["actor"] == "paralegal"


def test_names_resolve_case_and_whitespace_insensitively(conn):
    matter_open("  Project   X ", create=True)
    table_ingest("project x", "Entities", [col("Some Column", 1, CLEAN_FR)])
    assert column_read("PROJECT X", "entities", "some column")["name"] == "Some Column"
