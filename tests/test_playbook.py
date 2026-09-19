"""Parsing a Harvey playbook export, and the mechanical half of the authoring checklist.

The checks that matter most are the ones that stay quiet: a playbook following the authoring
conventions should produce nothing, or the findings are noise and get ignored.
"""

from __future__ import annotations

import pytest

from prompt_graph import playbook as pbm
from prompt_graph.findings import PromptGraphError

CLEAN = """
# AI Guidance
Document control: version 3, owner Head of Commercial, effective date 2026-09-01.
Absent a stated path on exhaustion, flag to the client and do not concede further.

## Limitation of Liability
#### Standard Position
ADD the below provision if not already otherwise addressed: "The breaching party shall be
liable only for direct damages arising out of any unauthorised use or disclosure."
#### Acceptable Positions
Mutual capACCEPT a mutual cap at two times fees paid in the preceding twelve months.
#### Unacceptable Positions
UncappedAny formulation leaving liability uncapped for ordinary breach.
### Guidance
Rule ID: mnda.liability.cap

Direct-damages-only is the house position.

Depends on: mnda.indemnity.general (trade-off)
On exhaustion: escalate to the deal partner with the counterparty's last position.
Source: risk-policy-v7 4.2 · Reviewed: 2026-09-18
### Required
Yes

## Indemnification
#### Standard Position
REJECT indemnification.
#### Acceptable Positions
Prevailing party costsADD prevailing party legal expenses on a final non-appealable order.
#### Unacceptable Positions
Broad indemnityAny indemnity covering third-party claims generally.
### Guidance
Rule ID: mnda.indemnity.general

Indemnities do not belong in a mutual NDA.

Depends on: mnda.liability.cap (trade-off)
### Required
No
"""


def test_parses_the_export_shape() -> None:
    pb = pbm.parse_markdown(CLEAN, name="clean")
    assert [r.name for r in pb.rules] == ["Limitation of Liability", "Indemnification"]
    lol = pb.rules[0]
    assert lol.required is True
    assert lol.acceptable and lol.unacceptable
    assert "direct damages" in lol.standard
    assert "Document control" in pb.preamble


def test_parses_the_guidance_conventions() -> None:
    lol = pbm.parse_markdown(CLEAN).rules[0]
    assert lol.rule_id == "mnda.liability.cap"
    assert lol.depends_on == [("mnda.indemnity.general", "trade-off")]
    assert lol.on_exhaustion and lol.on_exhaustion.startswith("escalate")
    assert lol.source == "risk-policy-v7 4.2" and lol.reviewed == "2026-09-18"


def test_a_conforming_playbook_is_quiet() -> None:
    """The point of the suite. Checks that always fire teach people to ignore them."""
    assert pbm.playbook_check(pbm.parse_markdown(CLEAN, name="clean")) == []


def test_label_and_body_are_split_despite_the_export_concatenating_them() -> None:
    label, body = pbm._split_label("Reasonable editsOK to accept reasonable edits.")
    assert label == "Reasonable edits"
    assert body == "OK to accept reasonable edits."
    # no boundary to find: the whole string is the body, not a guess
    assert pbm._split_label("all lowercase throughout") == (None, "all lowercase throughout")


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("Rule ID: mnda.liability.cap", "RULE_ID_MISSING"),
        (
            "#### Unacceptable Positions\nUncappedAny formulation leaving liability uncapped for ordinary breach.",
            "UNACCEPTABLE_NOT_STATED",
        ),
        ("Depends on: mnda.indemnity.general (trade-off)", "DEPENDENCY_REASON_MISSING"),
    ],
)
def test_removing_a_convention_raises_its_finding(mutation: str, code: str) -> None:
    broken = CLEAN.replace(mutation, "", 1)
    if code == "DEPENDENCY_REASON_MISSING":
        broken = CLEAN.replace(mutation, "Depends on: mnda.indemnity.general", 1)
    codes = {f.code for f in pbm.playbook_check(pbm.parse_markdown(broken))}
    assert code in codes


def test_dependency_on_a_rule_that_does_not_exist() -> None:
    broken = CLEAN.replace("mnda.indemnity.general (trade-off)", "mnda.nope.missing (trade-off)", 1)
    fs = [
        f
        for f in pbm.playbook_check(pbm.parse_markdown(broken))
        if f.code == "DEPENDS_ON_UNRESOLVED"
    ]
    assert len(fs) == 1 and fs[0].evidence["ref"] == "mnda.nope.missing"


def test_an_unspecified_deviation_is_flagged_but_a_substantive_one_is_not() -> None:
    bare = CLEAN.replace(
        "Mutual capACCEPT a mutual cap at two times fees paid in the preceding twelve months.",
        "Reasonable editsOK to accept reasonable edits.",
        1,
    )
    assert "DEVIATION_UNSPECIFIED" in {f.code for f in pbm.playbook_check(pbm.parse_markdown(bare))}
    # the same phrase carrying real content is not the same defect
    rich = CLEAN.replace(
        "Mutual capACCEPT a mutual cap at two times fees paid in the preceding twelve months.",
        "Reasonable editsACCEPT reasonable edits, and a mutual cap at two times fees paid.",
        1,
    )
    assert "DEVIATION_UNSPECIFIED" not in {
        f.code for f in pbm.playbook_check(pbm.parse_markdown(rich))
    }


def test_required_without_supplied_wording_is_flagged() -> None:
    """Insert-a-customary-provision leaves a model drafting the outbound redline."""
    vague = CLEAN.replace(
        'ADD the below provision if not already otherwise addressed: "The breaching party shall be\nliable only for direct damages arising out of any unauthorised use or disclosure."',
        "ADD a customary limitation of liability if not already addressed.",
        1,
    )
    codes = {f.code for f in pbm.playbook_check(pbm.parse_markdown(vague))}
    assert "ABSENCE_REMEDIATION_MISSING" in codes


def test_a_gate_on_another_rules_outcome_is_prose_not_structure() -> None:
    gated = CLEAN.replace(
        "Indemnities do not belong in a mutual NDA.",
        "This rule applies only when the liability fallback has been accepted with client approval.",
        1,
    )
    fs = [
        f
        for f in pbm.playbook_check(pbm.parse_markdown(gated))
        if f.code == "PROSE_SUBSTITUTES_FOR_STRUCTURE"
    ]
    assert len(fs) == 1


def test_one_sided_precedence_is_invisible_from_the_other_rule() -> None:
    one_sided = CLEAN.replace(
        "Indemnities do not belong in a mutual NDA.",
        "Indemnities do not belong in a mutual NDA.\n\nPrecedence: this rule governs over Limitation of Liability.",
        1,
    )
    fs = [
        f
        for f in pbm.playbook_check(pbm.parse_markdown(one_sided))
        if f.code == "PRECEDENCE_ONE_SIDED"
    ]
    assert len(fs) == 1 and fs[0].evidence["other"] == "Limitation of Liability"


def test_duplicate_rule_ids() -> None:
    dup = CLEAN.replace("Rule ID: mnda.indemnity.general", "Rule ID: mnda.liability.cap", 1)
    assert "RULE_ID_DUPLICATE" in {f.code for f in pbm.playbook_check(pbm.parse_markdown(dup))}


def test_missing_document_control_and_exhaustion_default() -> None:
    bare = CLEAN.split("## Limitation")[1]
    pb = pbm.parse_markdown(
        "## Limitation"
        + bare.replace(
            "On exhaustion: escalate to the deal partner with the counterparty's last position.", ""
        )
    )
    codes = {f.code for f in pbm.playbook_check(pb)}
    assert "DOCUMENT_CONTROL_MISSING" in codes
    assert "EXHAUSTION_DEFAULT_MISSING" in codes


def test_a_missing_or_unreadable_file_is_refused(tmp_path) -> None:
    with pytest.raises(PromptGraphError, match="No playbook at"):
        pbm.parse_docx(tmp_path / "absent.docx")
    junk = tmp_path / "junk.docx"
    junk.write_text("not a zip")
    with pytest.raises(PromptGraphError, match="not a readable"):
        pbm.parse_docx(junk)
