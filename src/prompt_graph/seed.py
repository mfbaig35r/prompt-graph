"""Load the Project Harbor demo matter from fixtures/demo_matter.json.

The matter and every name are fictional (they are the skill's worked example, extended to
four tables). It exists so the graph, staleness, evaluation, and coverage tools can be
demonstrated without client data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import coverage, evaluation, parameters, service
from .models import (
    AdvisoryRef,
    AssertionRecord,
    ColumnRecord,
    ConsumerBinding,
    EntityRecord,
    EvalRecord,
    SectionRecord,
    SourceRef,
    TableMeta,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "demo_matter.json"


def load_fixture(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or FIXTURE).read_text())


def load_demo(
    conn: sqlite3.Connection, path: Path | None = None, with_runs: bool = True
) -> dict[str, Any]:
    fx = load_fixture(path)
    m, _created = service.matter_open(
        conn,
        fx["matter"]["name"],
        create=True,
        objective=fx["matter"].get("objective"),
        side=fx["matter"].get("side"),
        actor="seed",
    )
    name = m["name"]
    std = fx.get("standard")
    if std:
        service.standard_set(
            conn,
            "matter",
            name,
            entities=[EntityRecord(**e) for e in std.get("entities", [])],
            objective=std.get("objective"),
            conventions=std.get("conventions"),
            date_pattern=std.get("date_pattern"),
            currency_pattern=std.get("currency_pattern"),
            change_note="Seeded demo matter",
            actor="seed",
        )
    ingests: list[dict[str, Any]] = []
    for t in fx["tables"]:
        cols = []
        for c in t["columns"]:
            adv = [AdvisoryRef(**a) for a in c.get("advisory_upstream", [])] or None
            cols.append(
                ColumnRecord(
                    **{k: v for k, v in c.items() if k != "advisory_upstream"},
                    advisory_upstream=adv,
                )
            )
        ingests.append(
            service.table_ingest(
                conn,
                name,
                t["name"],
                cols,
                TableMeta(**t.get("meta", {})),
                t.get("instructions"),
                source_type="drafted",
                actor="seed",
            )
        )
    for p in fx.get("parameters", []):
        parameters.parameter_set(
            conn,
            name,
            p["name"],
            p.get("value"),
            p.get("source_table"),
            p.get("source_column"),
            [ConsumerBinding(**c) for c in p.get("consumers", [])],
            actor="seed",
        )
    outline = fx.get("memo_outline")
    if outline:
        sections = [
            SectionRecord(
                name=s["name"],
                assertions=[
                    AssertionRecord(
                        text=a["text"],
                        kind=a["kind"],
                        note=a.get("note"),
                        sources=[SourceRef(**src) for src in a.get("sources", [])] or None,
                    )
                    for a in s["assertions"]
                ],
            )
            for s in outline["sections"]
        ]
        coverage.memo_outline_set(
            conn, name, sections, outline.get("name", "Diligence memo"), actor="seed"
        )
    if with_runs:
        for r in fx.get("runs", []):
            run = evaluation.run_record(
                conn,
                name,
                r["table"],
                r.get("started_at"),
                r.get("note"),
                r.get("evaluator"),
                r.get("corpus_note"),
                None,
                r.get("coverage_dimensions"),
                actor="seed",
            )
            if r.get("results"):
                evaluation.eval_record(
                    conn,
                    name,
                    r["table"],
                    [EvalRecord(**x) for x in r["results"]],
                    run["run_id"],
                    actor="seed",
                )
        for rev in fx.get("revisions", []):
            col = service.column_read(conn, name, rev["table"], rev["column"])
            text = col["prompt_text"]
            old, new = rev["replace"]
            if old in text:
                service.column_revise(
                    conn,
                    name,
                    rev["table"],
                    rev["column"],
                    prompt_text=text.replace(old, new),
                    change_note=rev.get("change_note"),
                    failure_class_addressed=rev.get("failure_class_addressed"),
                    actor="seed",
                )
    return {"matter": name, "tables": len(fx["tables"]), "ingests": ingests}
