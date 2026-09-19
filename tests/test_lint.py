"""Every prompt-level validation rule in requirements §8, matched to the skill's vocabulary."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from prompt_graph.constants import CHAR_LIMIT_ADVISORY, CHAR_LIMIT_HARD, FALLBACK_SYNONYMS
from prompt_graph.lint import PromptContext, check_prompt, fallback_terms_used

# The skill lives in its own repository beside this one; set LEGAL_REVIEW_SKILL_DIR to override.
SKILL_DIR = Path(
    os.environ.get(
        "LEGAL_REVIEW_SKILL_DIR",
        Path(__file__).resolve().parents[2] / "legal-review-table-builder-skill",
    )
)
COLS = [
    ("Document Type", 1),
    ("Principal Entity", 2),
    ("Execution Status", 3),
    ("Signatories", 4),
    ("Human Review Flags", 5),
]


def codes(findings):
    return sorted(f.code for f in findings)


def ctx(native_type="FreeResponse", options=None, name="Draft", position=3, cols=COLS):
    return PromptContext(native_type, options, name, position, cols)


# --- the skill's own worked examples must lint clean -----------------------------------


@pytest.mark.skipif(not SKILL_DIR.exists(), reason="skill sources not checked out")
def test_worked_examples_lint_clean():
    src = (SKILL_DIR / "references" / "worked-examples.md").read_text()
    blocks = re.findall(r"```markdown\n(.*?)```", src, re.S)
    exec_status, signatories = blocks[1], blocks[2]
    opts = [
        "Filed or issued",
        "Fully executed",
        "Partially executed",
        "Unsigned",
        "Not applicable",
        "Unable to determine",
    ]
    assert check_prompt(exec_status, ctx("Classify", opts, "Execution Status", 3)) == []
    assert check_prompt(signatories, ctx("FreeResponse", None, "Signatories", 4)) == []


# --- character limits --------------------------------------------------------------------


def test_hard_limit():
    text = "## Output format\n\nReturn x.\n" + "a" * CHAR_LIMIT_HARD
    assert "PROMPT_LENGTH_HARD" in codes(check_prompt(text, ctx()))
    assert "PROMPT_LENGTH_ADVISORY" not in codes(check_prompt(text, ctx()))


def test_advisory_limit():
    text = "## Output format\n\nReturn x.\n" + "a" * (CHAR_LIMIT_ADVISORY + 1)
    fs = check_prompt(text, ctx())
    assert codes(fs) == ["PROMPT_LENGTH_ADVISORY"]
    assert fs[0].evidence["char_count"] == len(text)


def test_exactly_at_limits_is_fine():
    base = "## Output format\n\nReturn x.\n"
    text = base + "a" * (CHAR_LIMIT_ADVISORY - len(base))
    assert not [c for c in codes(check_prompt(text, ctx())) if c.startswith("PROMPT_LENGTH")]


# --- fallback vocabulary -----------------------------------------------------------------


@pytest.mark.parametrize("syn", FALLBACK_SYNONYMS)
def test_each_synonym_is_flagged(syn):
    text = f"## Fallback rules\n\n- If silent, return `{syn}`.\n\n## Output format\n\nReturn the value."
    fs = [f for f in check_prompt(text, ctx()) if f.code == "FALLBACK_SYNONYM"]
    assert len(fs) == 1 and fs[0].evidence["term"] == syn


def test_synonym_in_prohibition_is_not_flagged():
    text = "## Rules\n\n- Do not return `N/A` or `None`; use `Not addressed`.\n\n## Output format\n\nReturn the value."
    assert "FALLBACK_SYNONYM" not in codes(check_prompt(text, ctx()))


def test_controlled_terms_not_flagged():
    text = "## Fallback rules\n\n- `Not addressed`, `Not applicable`, `Incorporated terms`, `Unable to determine`.\n\n## Output format\n\nReturn the value."
    assert "FALLBACK_SYNONYM" not in codes(check_prompt(text, ctx()))
    assert fallback_terms_used(text) == [
        "Not addressed",
        "Not applicable",
        "Incorporated terms",
        "Unable to determine",
    ]


# --- Not stated / Not addressed by type ---------------------------------------------------


@pytest.mark.parametrize("nt", ["FreeResponse", "Classify", "Verbatim"])
def test_not_stated_outside_typed_column(nt):
    text = "## Output format\n\nReturn `Not stated` when absent."
    assert "FALLBACK_NOT_STATED_UNTYPED" in codes(check_prompt(text, ctx(nt, ["A"])))


@pytest.mark.parametrize("nt", ["Date", "Number", "Currency", "Duration"])
def test_not_stated_inside_typed_column_is_fine(nt):
    text = "## Output format\n\nReturn `Not stated` when absent."
    assert "FALLBACK_NOT_STATED_UNTYPED" not in codes(check_prompt(text, ctx(nt)))


@pytest.mark.parametrize("nt", ["Date", "Number", "Currency", "Duration"])
def test_not_addressed_inside_typed_column(nt):
    text = "## Output format\n\nReturn `Not addressed` when silent."
    assert "FALLBACK_NOT_ADDRESSED_TYPED" in codes(check_prompt(text, ctx(nt)))


def test_not_addressed_in_free_response_is_fine():
    text = "## Output format\n\nReturn `Not addressed` when silent."
    assert "FALLBACK_NOT_ADDRESSED_TYPED" not in codes(check_prompt(text, ctx("FreeResponse")))


# --- Classify rules ------------------------------------------------------------------------


def test_classify_label_not_in_options():
    text = "## Rules\n\n- `Yes`: when present.\n- `Maybe`: when unclear.\n\n## Output format\n\nReturn only the exact configured option."
    fs = [
        f
        for f in check_prompt(text, ctx("Classify", ["Yes", "No"]))
        if f.code == "CLASSIFY_LABEL_NOT_CONFIGURED"
    ]
    assert len(fs) == 1 and fs[0].evidence["labels"] == ["Maybe"]


def test_classify_labels_that_are_fallbacks_or_options_are_fine():
    text = "## Rules\n\n- `Yes`\n- `Not applicable`\n- `Unable to determine`\n\n## Output format\n\nReturn only the exact configured option."
    assert "CLASSIFY_LABEL_NOT_CONFIGURED" not in codes(
        check_prompt(text, ctx("Classify", ["Yes", "No"]))
    )


def test_classify_em_dash_qualifier():
    text = "## Fallback rules\n\n- Return `Unable to determine — signature page missing`.\n\n## Output format\n\nReturn only the exact configured option."
    assert "CLASSIFY_QUALIFIER_PERMITTED" in codes(check_prompt(text, ctx("Classify", ["Yes"])))


def test_free_response_em_dash_qualifier_is_allowed():
    text = "## Fallback rules\n\n- Return `Unable to determine — signature page missing`.\n\n## Output format\n\nReturn the value."
    assert "CLASSIFY_QUALIFIER_PERMITTED" not in codes(check_prompt(text, ctx("FreeResponse")))


def test_classify_without_options_reported():
    assert "OPTIONS_MISSING" in codes(
        check_prompt("## Output format\n\nReturn the option.", ctx("Classify", None))
    )


# --- references ----------------------------------------------------------------------------


def test_unresolved_reference():
    text = "## Established results\n\n- Type: @Doc Kind\n\n## Output format\n\nReturn the value."
    fs = [f for f in check_prompt(text, ctx()) if f.code == "REF_UNRESOLVED"]
    assert len(fs) == 1 and fs[0].evidence["reference"] == "Doc Kind"


def test_forward_reference():
    text = "## Established results\n\n- Flags: @Human Review Flags\n\n## Output format\n\nReturn the value."
    fs = [f for f in check_prompt(text, ctx(position=2)) if f.code == "REF_FORWARD"]
    assert len(fs) == 1 and fs[0].evidence["reference"] == "Human Review Flags"


def test_backward_reference_is_fine():
    text = (
        "## Established results\n\n- Type: @Document Type\n\n## Output format\n\nReturn the value."
    )
    assert not [c for c in codes(check_prompt(text, ctx(position=2))) if c.startswith("REF_")]


def test_self_reference():
    text = "Use @Signatories.\n\n## Output format\n\nReturn the value."
    assert "REF_SELF" in codes(check_prompt(text, ctx(name="Signatories", position=4)))


def test_references_skipped_without_table_context():
    text = "Use @Whatever.\n\n## Output format\n\nReturn the value."
    assert not [
        c for c in codes(check_prompt(text, PromptContext("FreeResponse"))) if c.startswith("REF_")
    ]


# --- output contract and Markdown ----------------------------------------------------------


def test_output_contract_missing():
    assert "OUTPUT_CONTRACT_MISSING" in codes(check_prompt("## Task\n\nDescribe the thing.", ctx()))


def test_output_contract_via_return_sentence():
    assert "OUTPUT_CONTRACT_MISSING" not in codes(
        check_prompt("Describe the thing. Return the name only.", ctx())
    )


def test_markdown_in_cell_without_contract():
    text = "## Rules\n\n- Format the answer as a bulleted list.\n\n## Output format\n\nReturn plain text."
    assert "MARKDOWN_IN_CELL" in codes(check_prompt(text, ctx()))


def test_markdown_allowed_by_output_contract():
    text = "## Rules\n\n- Format the answer as a bulleted list.\n\n## Output format\n\nReturn a Markdown bulleted list."
    assert "MARKDOWN_IN_CELL" not in codes(check_prompt(text, ctx()))


def test_markdown_prohibition_is_not_flagged():
    text = (
        "## Rules\n\n- Do not use Markdown in the answer.\n\n## Output format\n\nReturn plain text."
    )
    assert "MARKDOWN_IN_CELL" not in codes(check_prompt(text, ctx()))


# --- finding shape --------------------------------------------------------------------------


def test_finding_shape_has_one_sentence_and_no_advice():
    text = "## Output format\n\nReturn `TBD`."
    f = check_prompt(text, ctx())[0]
    assert set(f.to_dict()) == {
        "code",
        "subject_type",
        "subject_id",
        "subject_name",
        "observation",
        "evidence",
        "remedy",
    }
    # remedy exists for the playbook family, which knows an authoring format well enough to say
    # where a missing thing goes. Nothing here does, so it stays empty rather than guessing.
    assert f.remedy is None
    assert f.observation.count(". ") == 0 and f.observation.endswith(".")
    for word in ("should", "must", "recommend", "fix", "critical", "severe"):
        assert word not in f.observation.lower()


# --- character-count rules and dead references (2026-09-04 bundle) -----------------------


def test_character_count_rule():
    text = (
        "## Rules\n\n- Truncate the name to 20 characters.\n\n## Output format\n\nReturn the value."
    )
    fs = [f for f in check_prompt(text, ctx()) if f.code == "CHARACTER_COUNT_RULE"]
    assert len(fs) == 1 and fs[0].evidence["lines"] == ["- Truncate the name to 20 characters."]


def test_word_limit_is_not_a_character_count_rule():
    text = (
        "## Output format\n\nReturn no more than 120 words. Do not truncate to a character count."
    )
    assert "CHARACTER_COUNT_RULE" not in codes(check_prompt(text, ctx()))


def test_dead_reference_declared_but_unused():
    text = (
        "## Established results\n\n- Document Type: @Document Type\n- Execution Status: @Execution Status\n\n"
        "## Task\n\nIf Execution Status is `Unsigned`, return `Not applicable`.\n\n## Output format\n\nReturn the value."
    )
    fs = [f for f in check_prompt(text, ctx(position=4)) if f.code == "DEAD_REFERENCE"]
    assert [f.evidence["reference"] for f in fs] == ["Document Type"]


def test_reference_used_inline_is_not_dead():
    text = "## Task\n\nIf @Execution Status is `Unsigned`, return `Not applicable`.\n\n## Output format\n\nReturn the value."
    assert "DEAD_REFERENCE" not in codes(check_prompt(text, ctx(position=4)))


def test_generic_established_result_phrase_counts_as_use():
    text = (
        "## Established results\n\n- Document Type: @Document Type\n\n"
        "## Rules\n\n- Report `Upstream unresolved` when any established result is `Unable to determine`.\n\n"
        "## Output format\n\nReturn the value."
    )
    assert "DEAD_REFERENCE" not in codes(check_prompt(text, ctx(position=4)))


def test_dead_reference_skipped_without_table_context():
    text = "## Established results\n\n- X: @Document Type\n\n## Output format\n\nReturn the value."
    assert "DEAD_REFERENCE" not in codes(check_prompt(text, PromptContext("FreeResponse")))
