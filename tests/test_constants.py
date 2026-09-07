"""The controlled vocabularies must match the skill's reference files exactly."""

from __future__ import annotations

import pytest

from prompt_graph.constants import COVERAGE_DIMENSIONS, FAILURE_CLASSES, FALLBACK_VOCABULARY
from tests.test_lint import SKILL_DIR

pytestmark = pytest.mark.skipif(
    not SKILL_DIR.exists(), reason="skill not checked out beside this repo"
)


def _table_first_column(path, header: str) -> list[str]:
    rows = []
    in_table = False
    for line in path.read_text().splitlines():
        if line.startswith("| " + header):
            in_table = True
            continue
        if in_table and line.startswith("| ---"):
            continue
        if in_table and line.startswith("| "):
            rows.append(line.split("|")[1].strip())
        elif in_table and not line.strip():
            break
    return rows


def test_failure_taxonomy_matches_skill_table_in_order():
    labels = _table_first_column(SKILL_DIR / "references" / "evaluation.md", "Failure class")
    assert list(FAILURE_CLASSES.values()) == labels


def test_fallback_vocabulary_matches_skill():
    text = (SKILL_DIR / "SKILL.md").read_text()
    for term in FALLBACK_VOCABULARY:
        assert f"- `{term}`:" in text
    assert len(FALLBACK_VOCABULARY) == 5


def test_coverage_dimensions_match_evaluation_log_template():
    text = (SKILL_DIR / "assets" / "evaluation-log-template.md").read_text()
    ticks = [line[6:].strip() for line in text.splitlines() if line.startswith("- [ ] ")]
    labels = [
        label if not grouping else label + " (if grouping is used)"
        for _, label, grouping in COVERAGE_DIMENSIONS
    ]
    assert labels == ticks
