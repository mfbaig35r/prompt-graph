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


def test_a_deviations_title_survives() -> None:
    """Word puts a line break between a deviation's title and its body inside one paragraph.
    Flattening the document to lines lost it, and the title was then discarded as a parsing
    artefact, which silently dropped the name of every fallback in the playbook."""
    label, body = pbm.split_label(
        "Consent requirement for limited partners\nOK to accept, if client has not said otherwise."
    )
    assert label == "Consent requirement for limited partners"
    assert body == "OK to accept, if client has not said otherwise."


def test_a_flattened_entry_falls_back_to_guessing_the_join() -> None:
    label, body = pbm.split_label("Reasonable editsOK to accept reasonable edits.")
    assert label == "Reasonable edits"
    assert body == "OK to accept reasonable edits."
    # no boundary to find: the whole string is the body, not a guess
    assert pbm.split_label("all lowercase throughout") == (None, "all lowercase throughout")


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


# --- rename detection -------------------------------------------------------

TWO_RULES = """
# AI Guidance
Document control: version 1, owner Legal. On exhaustion, escalate to the client.

## General Terminology
#### Standard Position
Throughout the Agreement change "cause" to "direct".
#### Acceptable Positions
Narrow scopeACCEPT the change limited to the confidentiality covenants.
#### Unacceptable Positions
No changeLeaving "best efforts" unmodified throughout.
### Guidance
Rule ID: mnda.terms.general

These are defaults. A specific rule may displace them where it expressly says so.

Precedence: the exception is Representative's Adherence.
### Required
Yes

## Representative's Adherence
#### Standard Position
ADD the below provision if not already addressed: "Recipient shall direct its Representatives
to comply with the confidentiality obligations of this Agreement."
#### Acceptable Positions
Cause standardACCEPT "cause" in place of "direct" where the counterparty insists.
#### Unacceptable Positions
No obligationNo obligation on Representatives at all.
### Guidance
Rule ID: mnda.reps.adherence

This rule is an express exception to General Terminology, which otherwise requires "direct".
### Required
Yes
"""


def test_a_stable_id_makes_a_rename_a_fact() -> None:
    after = TWO_RULES.replace("## General Terminology", "## Drafting Conventions", 1)
    d = pbm.playbook_diff(pbm.parse_markdown(TWO_RULES, "v1"), pbm.parse_markdown(after, "v2"))
    renames = [f for f in d["findings"] if f.code == "RULE_RENAMED"]
    assert len(renames) == 1
    assert renames[0].evidence["by"] == "rule_id"
    assert d["counts"]["renamed"] == 1 and d["counts"]["removed"] == 0


def test_without_an_id_a_rename_is_inferred_from_content_and_scored() -> None:
    """The real case today: no playbook has adopted rule ids, so identity comes from content."""
    v1 = TWO_RULES.replace("Rule ID: mnda.terms.general\n", "")
    v2 = v1.replace("## General Terminology", "## Drafting Conventions", 1)
    d = pbm.playbook_diff(pbm.parse_markdown(v1, "v1"), pbm.parse_markdown(v2, "v2"))
    renames = [f for f in d["findings"] if f.code == "RULE_RENAMED"]
    assert len(renames) == 1
    assert renames[0].evidence["by"] == "content"
    assert renames[0].evidence["match"] >= 0.6


def test_a_rename_surfaces_the_reference_it_broke() -> None:
    """The whole point. The other rule still names the old one in prose, and nothing in Harvey
    would notice."""
    after = TWO_RULES.replace("## General Terminology", "## Drafting Conventions", 1)
    d = pbm.playbook_diff(pbm.parse_markdown(TWO_RULES, "v1"), pbm.parse_markdown(after, "v2"))
    broken = [f for f in d["findings"] if f.code == "REFERENCE_TO_RENAMED_RULE"]
    assert len(broken) == 1
    assert broken[0].evidence["now"] == "Drafting Conventions"
    assert "Representative" in broken[0].subject_name


def test_a_changed_rule_id_breaks_its_dependents() -> None:
    after = TWO_RULES.replace("Rule ID: mnda.terms.general", "Rule ID: mnda.drafting.general", 1)
    d = pbm.playbook_diff(pbm.parse_markdown(TWO_RULES, "v1"), pbm.parse_markdown(after, "v2"))
    assert "RULE_ID_CHANGED" in {f.code for f in d["findings"]}


def test_a_removed_rule_still_referenced() -> None:
    after = TWO_RULES.split("## Representative's Adherence")[0]
    d = pbm.playbook_diff(pbm.parse_markdown(TWO_RULES, "v1"), pbm.parse_markdown(after, "v2"))
    removed = [f for f in d["findings"] if f.code == "RULE_REMOVED"]
    assert len(removed) == 1 and removed[0].subject_name == "Representative's Adherence"


def test_an_unchanged_playbook_diffs_to_nothing() -> None:
    d = pbm.playbook_diff(pbm.parse_markdown(TWO_RULES, "v1"), pbm.parse_markdown(TWO_RULES, "v2"))
    assert d["finding_count"] == 0
    assert d["counts"] == {"added": 0, "removed": 0, "renamed": 0, "changed": 0, "unchanged": 2}


def test_a_rule_still_using_its_own_former_name_is_a_different_defect() -> None:
    """Conflating this with a broken cross-reference sends a reader looking for a pointer that
    never existed."""
    v1 = TWO_RULES.replace("These are defaults.", "These are the General Terminology defaults.", 1)
    v2 = v1.replace("## General Terminology", "## Drafting Conventions", 1)
    d = pbm.playbook_diff(pbm.parse_markdown(v1, "v1"), pbm.parse_markdown(v2, "v2"))
    codes = {f.code for f in d["findings"]}
    assert "RENAMED_RULE_SELF_REFERENCE" in codes
    self_ref = next(f for f in d["findings"] if f.code == "RENAMED_RULE_SELF_REFERENCE")
    assert self_ref.subject_name == "Drafting Conventions"
    assert self_ref.evidence["former_name"] == "general terminology"
    # the genuine cross-reference from the other rule is still reported separately
    cross = [f for f in d["findings"] if f.code == "REFERENCE_TO_RENAMED_RULE"]
    assert len(cross) == 1 and cross[0].subject_name == "Representative's Adherence"


def test_a_preamble_restating_a_rules_position_is_two_sources_of_truth() -> None:
    with_pre = CLEAN.replace(
        "Absent a stated path on exhaustion, flag to the client and do not concede further.",
        "Absent a stated path on exhaustion, flag to the client. Key provisions: Limitation of "
        "Liability (always add a provision limiting the breaching party to direct damages "
        "arising out of any unauthorised use or disclosure).",
        1,
    )
    fs = [
        f
        for f in pbm.playbook_check(pbm.parse_markdown(with_pre))
        if f.code == "PREAMBLE_RESTATES_RULE"
    ]
    assert len(fs) == 1 and fs[0].subject_name == "Limitation of Liability"
    # a preamble that merely mentions the rule without restating it is not the same defect
    mention = CLEAN.replace(
        "Absent a stated path on exhaustion, flag to the client and do not concede further.",
        "Absent a stated path on exhaustion, escalate. See Limitation of Liability for the ladder.",
        1,
    )
    assert "PREAMBLE_RESTATES_RULE" not in {
        f.code for f in pbm.playbook_check(pbm.parse_markdown(mention))
    }


def test_a_finite_ceiling_against_an_unbounded_floor_leaves_a_hole() -> None:
    """Accept up to three years, refuse an indefinite term, and four years is unaddressed."""
    dur = CLEAN.replace(
        "Mutual capACCEPT a mutual cap at two times fees paid in the preceding twelve months.",
        "Up to 3 yearsACCEPT up to 3 years or until end of the Agreement term.",
        1,
    ).replace(
        "UncappedAny formulation leaving liability uncapped for ordinary breach.",
        "Indefinite termLanguage suggesting that the term is indefinite.",
        1,
    )
    fs = [f for f in pbm.playbook_check(pbm.parse_markdown(dur)) if f.code == "LADDER_GAP"]
    assert len(fs) == 1
    assert fs[0].evidence["ceiling"].endswith("3 years")
    assert fs[0].evidence["unbounded"].lower().startswith("indefinite")


def test_a_categorical_pair_has_no_interval_to_leave_open() -> None:
    """Advice of counsel against opinion of counsel is not a scale, so there is no gap."""
    cat = CLEAN.replace(
        "Mutual capACCEPT a mutual cap at two times fees paid in the preceding twelve months.",
        "Advice of counselOK to condition upon advice of counsel.",
        1,
    ).replace(
        "UncappedAny formulation leaving liability uncapped for ordinary breach.",
        "Opinion of counselConditioning disclosure on opinion of counsel.",
        1,
    )
    assert "LADDER_GAP" not in {f.code for f in pbm.playbook_check(pbm.parse_markdown(cat))}


def test_every_playbook_finding_says_where_the_missing_thing_goes() -> None:
    """A remedy names a location and a shape. It never drafts a position, which is why the
    findings whose answer is a legal judgment say so instead of inventing one."""
    pb = pbm.parse_markdown(CLEAN.replace("Rule ID: mnda.liability.cap", "", 1))
    fs = pbm.playbook_check(pb)
    assert fs and all(f.remedy for f in fs)
    unacceptable = pbm.playbook_check(
        pbm.parse_markdown(
            CLEAN.replace(
                "#### Unacceptable Positions\nUncappedAny formulation leaving liability uncapped for ordinary breach.",
                "",
                1,
            )
        )
    )
    remedy = next(f.remedy for f in unacceptable if f.code == "UNACCEPTABLE_NOT_STATED")
    assert "judgment about this deal" in remedy


def test_a_finding_from_another_family_carries_no_remedy() -> None:
    """The field is optional and the playbook family is the only one that populates it."""
    from prompt_graph.findings import Finding

    assert Finding("X", "rule", None, "n", "obs").remedy is None
