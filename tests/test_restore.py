"""matter_import: the inverse of matter_export.

The round trip is the real proof. A matter authored in chat has no other source, so if import
drops something there is nothing to compare against later and the loss is silent.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from prompt_graph import db, export, restore
from prompt_graph.findings import PromptGraphError
from tests.conftest import HARBOR


def _fresh(tmp_path: Path, name: str = "target.db") -> sqlite3.Connection:
    return db.connect(tmp_path / name)


def test_round_trip_preserves_every_count(harbor_evaluated, tmp_path: Path) -> None:
    before = export.matter_export(harbor_evaluated, HARBOR, inline=True)["counts"]
    doc = export.build_export(harbor_evaluated, HARBOR)

    dst = _fresh(tmp_path)
    res = restore.matter_import(dst, document=doc)
    after = export.matter_export(dst, HARBOR, inline=True)["counts"]

    for key in before:
        if key == "provenance_events":
            # the import records one audit event of its own
            assert after[key] == before[key] + 1, key
        else:
            assert after[key] == before[key], key
    assert res["counts"]["provenance_orphaned"] == 0


def test_round_trip_preserves_prompt_history_and_current_flag(
    harbor_evaluated, tmp_path: Path
) -> None:
    doc = export.build_export(harbor_evaluated, HARBOR)
    dst = _fresh(tmp_path)
    restore.matter_import(dst, document=doc)
    rows = dst.execute(
        """SELECT pv.version, pv.is_current, pv.change_note FROM prompt_version pv
           JOIN column_def c ON c.id=pv.column_id JOIN review_table rt ON rt.id=c.table_id
           JOIN matter m ON m.id=rt.matter_id
           WHERE m.name=? AND c.name='Execution Status' ORDER BY pv.major, pv.minor""",
        (HARBOR,),
    ).fetchall()
    assert [r["version"] for r in rows] == ["v1.0", "v1.1"]
    assert [bool(r["is_current"]) for r in rows] == [False, True]


def test_round_trip_preserves_outline_history(harbor_evaluated, tmp_path: Path) -> None:
    """Superseded outlines travel too. Without them the provenance recording each revision has
    no subject to point at, and the import silently forgets the outline was ever revised."""
    doc = export.build_export(harbor_evaluated, HARBOR)
    dst = _fresh(tmp_path)
    restore.matter_import(dst, document=doc)
    n_src = harbor_evaluated.execute(
        "SELECT COUNT(*) FROM memo_outline WHERE matter_id=(SELECT id FROM matter WHERE name=?)",
        (HARBOR,),
    ).fetchone()[0]
    n_dst = dst.execute(
        "SELECT COUNT(*) FROM memo_outline WHERE matter_id=(SELECT id FROM matter WHERE name=?)",
        (HARBOR,),
    ).fetchone()[0]
    assert n_dst == n_src
    assert (
        dst.execute(
            "SELECT COUNT(*) FROM memo_outline WHERE is_current=1 AND matter_id=(SELECT id FROM matter WHERE name=?)",
            (HARBOR,),
        ).fetchone()[0]
        == 1
    )


def test_dependencies_point_at_the_new_columns(harbor_evaluated, tmp_path: Path) -> None:
    """Edges travel by name. A remap that silently missed would leave the graph pointing at
    whatever now holds the old id, which reads as a plausible but wrong picture."""
    doc = export.build_export(harbor_evaluated, HARBOR)
    dst = _fresh(tmp_path)
    restore.matter_import(dst, document=doc)
    dangling = dst.execute(
        """SELECT COUNT(*) FROM dependency d
           LEFT JOIN column_def a ON a.id=d.from_column_id
           LEFT JOIN column_def b ON b.id=d.to_column_id
           WHERE a.id IS NULL OR b.id IS NULL"""
    ).fetchone()[0]
    assert dangling == 0
    cross = dst.execute(
        """SELECT COUNT(*) FROM dependency d
           JOIN column_def a ON a.id=d.from_column_id JOIN review_table ra ON ra.id=a.table_id
           JOIN column_def b ON b.id=d.to_column_id JOIN review_table rb ON rb.id=b.table_id
           WHERE ra.matter_id != rb.matter_id"""
    ).fetchone()[0]
    assert cross == 0


def test_import_from_a_file(harbor_evaluated, tmp_path: Path) -> None:
    out = export.matter_export(harbor_evaluated, HARBOR, write_to=str(tmp_path))
    dst = _fresh(tmp_path)
    res = restore.matter_import(dst, path=out["path"])
    assert res["matter"] == HARBOR and res["counts"]["tables"] == 4


def test_existing_matter_is_refused_then_named_aside(harbor_evaluated, tmp_path: Path) -> None:
    doc = export.build_export(harbor_evaluated, HARBOR)
    dst = _fresh(tmp_path)
    restore.matter_import(dst, document=doc)
    with pytest.raises(PromptGraphError, match="already exists"):
        restore.matter_import(dst, document=doc)
    res = restore.matter_import(dst, document=doc, as_matter="Project Harbor (copy)")
    assert res["matter"] == "Project Harbor (copy)"
    assert dst.execute("SELECT COUNT(*) FROM matter").fetchone()[0] == 2


def test_replace_overwrites_without_orphaning_rows(harbor_evaluated, tmp_path: Path) -> None:
    doc = export.build_export(harbor_evaluated, HARBOR)
    dst = _fresh(tmp_path)
    restore.matter_import(dst, document=doc)
    first = dst.execute("SELECT COUNT(*) FROM column_def").fetchone()[0]
    res = restore.matter_import(dst, document=doc, replace=True)
    assert res["replaced"] is True
    assert dst.execute("SELECT COUNT(*) FROM matter").fetchone()[0] == 1
    assert dst.execute("SELECT COUNT(*) FROM column_def").fetchone()[0] == first
    for table, col in (
        ("prompt_version", "column_id"),
        ("assertion_source", "column_id"),
        ("dependency", "from_column_id"),
    ):
        orphans = dst.execute(
            f"SELECT COUNT(*) FROM {table} t LEFT JOIN column_def c ON c.id=t.{col} WHERE c.id IS NULL"
        ).fetchone()[0]
        assert orphans == 0, table


def test_a_failed_import_leaves_nothing_behind(harbor_evaluated, tmp_path: Path) -> None:
    """The whole import is one transaction. A half-written matter would be worse than none."""
    doc = export.build_export(harbor_evaluated, HARBOR)
    doc["tables"][1]["columns"][0]["native_type"] = None  # NOT NULL violation, mid-insert
    dst = _fresh(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        restore.matter_import(dst, document=doc)
    assert dst.execute("SELECT COUNT(*) FROM matter").fetchone()[0] == 0
    assert dst.execute("SELECT COUNT(*) FROM review_table").fetchone()[0] == 0
    assert dst.execute("SELECT COUNT(*) FROM column_def").fetchone()[0] == 0


def test_unreadable_documents_are_refused(tmp_path: Path) -> None:
    dst = _fresh(tmp_path)
    with pytest.raises(PromptGraphError, match="exactly one of"):
        restore.matter_import(dst)
    with pytest.raises(PromptGraphError, match="No export file"):
        restore.matter_import(dst, path=str(tmp_path / "absent.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(PromptGraphError, match="not valid JSON"):
        restore.matter_import(dst, path=str(bad))
    future = tmp_path / "future.json"
    future.write_text(json.dumps({"export_format_version": 99, "matter": {"name": "X"}}))
    with pytest.raises(PromptGraphError, match="not readable by this build"):
        restore.matter_import(dst, path=str(future))
