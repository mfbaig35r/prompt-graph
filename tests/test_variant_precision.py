"""Precision of the name-variant heuristic, measured rather than asserted.

The check guesses whether two similarly named columns are the same concept. A guess with no
measured precision trains people to ignore it, which is how lint tools die. This replays a
hand-labelled set of real cases through the real check and holds the grade to a floor.

The cases carry column names, roles and types only, no prompt text, and are reconstructed as a
synthetic matter so the test runs anywhere without the corpus database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt_graph.models import ColumnRecord, TableMeta
from prompt_graph.server import matter_open, suite_check, table_ingest
from tests.conftest import CLEAN_FR, HARBOR

LABELS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "name_variant_labels.json").read_text()
)

# Floors, not targets: a change that improves the grade should pass, one that degrades it fails.
MIN_STRONG_PRECISION = 0.90  # of clusters graded strong, share that really are one concept
MIN_POSSIBLE_PRECISION = 0.80  # of clusters graded possible, share that really are different
MIN_GRADED_CORRECTLY = 0.85  # of all labelled clusters, share graded on the right side


@pytest.fixture()
def labelled(conn):
    """Rebuild every labelled case as its own table, so names cluster exactly as they did."""
    matter_open(HARBOR, create=True)
    n = 0
    for case in LABELS["cases"]:
        for mm in case["members"]:
            n += 1
            table_ingest(
                HARBOR,
                f"T{n:03d} {mm['table']}",
                [
                    ColumnRecord(
                        name=mm["column"],
                        position=1,
                        prompt_text=CLEAN_FR,
                        native_type=mm["native_type"],
                        role=mm["role"],
                    )
                ],
                table_meta=TableMeta(review_unit="one document"),
            )
    return conn


def _graded(labelled):
    """Map each labelled case to the confidence the check gave it."""
    found = {
        "|".join(f["evidence"]["names"]): f["evidence"]["confidence"]
        for f in suite_check(HARBOR)["findings"]
        if f["code"] == "CONCEPT_NAME_VARIANT"
    }
    out = []
    for case in LABELS["cases"]:
        if case["label"] == "unclear":
            continue  # excluded from the denominator rather than forced into a binary
        out.append((case, found.get("|".join(case["names"]))))
    return out


def test_every_labelled_case_is_still_detected(labelled):
    """A case that stops being reported at all is a silent loss of coverage."""
    missing = [c["names"] for c, conf in _graded(labelled) if conf is None]
    assert not missing, f"no longer reported: {missing}"


def test_strong_precision(labelled):
    strong = [(c, conf) for c, conf in _graded(labelled) if conf == "strong"]
    right = [c for c, _ in strong if c["label"] == "same"]
    precision = len(right) / len(strong)
    assert precision >= MIN_STRONG_PRECISION, (
        f"strong precision {precision:.0%} below floor {MIN_STRONG_PRECISION:.0%}; "
        f"wrongly strong: {[c['names'] for c, _ in strong if c['label'] != 'same']}"
    )


def test_possible_precision(labelled):
    possible = [(c, conf) for c, conf in _graded(labelled) if conf == "possible"]
    right = [c for c, _ in possible if c["label"] == "different"]
    precision = len(right) / len(possible)
    assert precision >= MIN_POSSIBLE_PRECISION, (
        f"possible precision {precision:.0%} below floor {MIN_POSSIBLE_PRECISION:.0%}; "
        f"wrongly possible: {[c['names'] for c, _ in possible if c['label'] != 'different']}"
    )


def test_overall_grade(labelled):
    graded = _graded(labelled)
    correct = [
        c
        for c, conf in graded
        if (conf == "strong" and c["label"] == "same")
        or (conf == "possible" and c["label"] == "different")
    ]
    rate = len(correct) / len(graded)
    assert rate >= MIN_GRADED_CORRECTLY, (
        f"{rate:.0%} graded correctly, floor {MIN_GRADED_CORRECTLY:.0%}"
    )
