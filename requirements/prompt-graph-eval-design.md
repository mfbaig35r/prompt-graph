# prompt-graph — evaluation design

**Extends:** `prompt-graph-mcp-requirements.md`, `prompt-graph-addendum-a.md`
**Date:** 2026-09-15
**Status:** proposal. Nothing here is built. The evaluation machinery (`run_record`,
`eval_record`, `run_compare`, `failures_summary`) exists and has never been used: 0 runs, 0 eval
results, 0 run snapshots across both matters.

Covers what the evaluation layer needs before it is run in anger, argued from the schema as it
stands rather than from general practice. Measurements taken 2026-09-15 against the live database
opened `mode=ro`.

---

## E.0 What the schema already gets right

Two things, stated first because the rest of this document is a list of gaps and they would
otherwise be lost.

**The failure taxonomy is a diagnostic vocabulary, not a flag.** Nineteen classes
(`scope_leakage`, `evidence_overstatement`, `silence_uncertainty_error`, `holder_direction_error`
and the rest) with alias normalisation for the spellings a model will actually submit. Most eval
systems record that something failed. This one records *how*, in terms that map to a fix. That is
the expensive half of a failure taxonomy and it is already done.

**`run_snapshot` pins the inputs per column per run.** Both `prompt_version_id` and
`instructions_version_id`, primary-keyed on `(run_id, column_id)`. Every result is therefore
traceable to the exact prompt text and the exact table instructions that produced it. That is
real provenance, and E.5 is only possible to ask for because this already exists.

---

## E.1 The blocking gap: nothing records what the right answer was

`eval_result` holds `expected_behavior` (free text), `actual_answer`, and `passed` (an integer
boolean supplied by a human). **There is no `expected_answer`.**

The consequence is not that scoring is manual. It is that **scoring cannot be repeated.** Revise a
prompt and a human must re-judge every affected row from scratch, because nothing in the database
records what "correct" meant for that document. Evaluation cost therefore scales with attorney
time rather than compute, and on an 832-column corpus the cost of a prompt change, rather than its
value, becomes the thing that decides whether the change is made.

This also makes `passed` the one field in the entire system that is a verdict rather than a
finding. Everywhere else the server records observations with evidence and leaves judgment to a
person. Here the most consequential field is a bare boolean whose basis is unrecorded prose.

### What storing it would buy, measured

832 active columns across both matters:

| Native type | Columns | Share | Machine-scorable |
| --- | --- | --- | --- |
| FreeResponse | 502 | 60.3% | no |
| Classify | 225 | 27.0% | yes |
| Date | 67 | 8.1% | yes |
| Verbatim | 25 | 3.0% | yes, after normalisation |
| Currency | 11 | 1.3% | yes |
| Duration | 2 | 0.2% | yes |

**330 columns (39.7%) become machine-scored on the day the field exists.** And the Classify
cohort is genuinely ready rather than nominally ready: **zero of the 225 Classify columns lack a
configured option set**, so every one of them can be scored against its own menu immediately.

Two cautions on the typed cohort. The 25 Verbatim columns require ligature and hyphen
normalisation before comparison or exact match will fail on answers that are in fact correct.
And the native types are inferred from prompt wording, never confirmed against Harvey, so a
`match_mode` of `exact` on a column whose real type is something else will produce confident
nonsense.

---

## E.2 The 502 FreeResponse columns are partly a schema finding

The obvious route to scoring the remaining 60% is an LLM judge. It should not be the first move:
a judge shares the failure modes of the system it judges, and `evidence_overstatement` is
precisely the class a judge is worst at detecting, because overstatement reads as confidence.

The prior question is how many of those 502 should be FreeResponse at all. Broken down by role:

| Role of the FreeResponse column | Count | Read |
| --- | --- | --- |
| orientation | 274 | mixed; some genuinely prose, some are unconfigured menus |
| **extraction** | **197** | **the real candidates** |
| validation | 18 | mixed |
| human_review | 13 | prose by design, leave alone |

**An extraction column returning prose is the case worth interrogating.** Extraction pulls one
substantive fact; a substantive fact returning unconstrained text is the classic symptom of a
column that was never typed. The UI glossary already states the cost in the other direction:
FreeResponse "cannot be filtered reliably", so these columns are also the ones that cannot be
aggregated in a memo.

That makes conversion a double win and suggests a seventh `suite_check` family: flag extraction
columns whose native type is FreeResponse, as a finding with evidence, not a verdict. Some will be
correct as prose. The point is that nothing currently asks.

Notably, this is the inverse of the usual eval complaint. The problem is not that the evaluation
is too weak for the corpus. It is that part of the corpus is shaped so that no evaluation can be
strong.

---

## E.3 The absence axis is not measured

`passed` is a single boolean, but diligence has a severe harm asymmetry: reporting a
change-of-control provision that does not exist is a categorically different failure from missing
one that does. A single accuracy figure averages those together and hides the one that matters.

This requires precision and recall reported separately, which in turn requires **negative
examples**: documents that genuinely lack the provision the column asks about. A test set assembled
by finding good examples of each provision is all-positive by construction, and an all-positive
test set cannot detect hallucination at all. The failure is invisible rather than small.

`silence_uncertainty_error` already exists in the taxonomy, so the failure mode was anticipated.
Nothing in the schema obliges the test set to contain the cases that trigger it. `eval_result`
needs to record whether the document was expected to contain the thing, so that a wrong answer on
an absent provision is countable as its own rate.

---

## E.4 Labeller identity, and why the score is currently unfalsifiable

`evaluator` sits on `run`, not on `eval_result`. There is therefore no way to record that two
people labelled the same row, and no way to measure whether they agreed.

In legal this matters more than in most domains, because correctness is contested rather than
merely unknown. If two attorneys disagree on 15% of rows, a reported accuracy of 90% sits inside
the noise floor of its own ground truth and means nothing. The number is not wrong so much as
unfalsifiable.

Double-labelling a subset and reporting the agreement rate beside the score is the standard
remedy, is cheap (a few dozen rows), and is **the single highest-credibility addition available
for an attorney audience.** It is what converts "the tool says 90%" into a claim that survives a
partner pushing on it.

---

## E.5 Provenance is asymmetric: nothing pins Harvey's side

`run_snapshot` pins the prompt version and the instructions version. `run` records `started_at`,
`evaluator`, `corpus_note` and a document set snapshot. **No field records Harvey's model or
platform version.**

So the system detects its own inputs changing and is blind to the vendor's. When Harvey updates a
model underneath the matter, every stored result silently becomes incomparable to every new one,
and the staleness machinery reports nothing, because no prompt changed. Freshness as built answers
"did we change?" and cannot answer "did they?".

Harvey may expose no version identifier at all, which is consistent with the rest of the API
surface. The fallback is to record the date, treat elapsed time as a weak proxy, and keep a small
golden set that is periodically re-run unchanged, where **an unexplained delta on fixed inputs is
itself the drift signal**. That is only possible once E.1 exists, because re-running a golden set
requires scoring without a human.

---

## E.6 Sampling frame and tiering

**Sampling frame.** `test_document` is a bare string. Nothing records how those documents were
chosen, so nothing distinguishes a result that generalises from one drawn from the twenty easiest
documents to hand. The selection basis needs to be recorded on the run, and selection should be
stratified by document type.

**Tiering.** At 20 completions per minute per organisation, a full-corpus evaluation is a matter
of hours, so a single undifferentiated "eval" will be skipped exactly when someone is iterating
quickly. Two tiers: a small smoke set per prompt change, the full set per release. The tier a run
belongs to should be recorded, so that a smoke result is never mistaken for a release result.

---

## E.7 Schema delta

Additive, in the repository's existing convention. Migration number depends on ordering: the
contract-review extension is written and unapplied, so this is **4 or 5**.

```sql
ALTER TABLE eval_result ADD COLUMN expected_answer   TEXT;
ALTER TABLE eval_result ADD COLUMN match_mode        TEXT;  -- exact|normalized|set_member|numeric|date|judged
ALTER TABLE eval_result ADD COLUMN scored_by         TEXT;  -- computed|human
ALTER TABLE eval_result ADD COLUMN labeller          TEXT;  -- per row; enables agreement (E.4)
ALTER TABLE eval_result ADD COLUMN expected_present  INTEGER; -- 0 = document genuinely lacks it (E.3)

ALTER TABLE run ADD COLUMN platform_version TEXT;  -- Harvey's side; NULL when unavailable (E.5)
ALTER TABLE run ADD COLUMN sampling_frame   TEXT;  -- how documents were chosen (E.6)
ALTER TABLE run ADD COLUMN tier             TEXT;  -- smoke|release (E.6)
```

`passed` is retained and becomes computed wherever `match_mode` is not `judged`, with `scored_by`
recording which. Nothing existing breaks: every column is nullable and every current write path
remains valid.

---

## E.8 Sequencing

1. **`expected_answer` and `match_mode` first**, before any evaluation is recorded. Retrofitting
   means re-labelling, which is the one cost that cannot be recovered later.
2. **One honest manual evaluation of a single table**, then re-read this document. Six gaps are
   described here and a real run will show which two actually bite. Designing the whole evaluation
   system before running any of it is the failure mode this project is otherwise good at avoiding.
3. Negative examples (E.3) and per-row labellers (E.4) in the first real run, since both are about
   how the test set is *assembled* and cannot be added afterwards without redoing it.
4. Platform version, sampling frame and tier (E.5, E.6) whenever convenient; they are recording
   fields, not design constraints.
5. The extraction-returns-FreeResponse check (E.2) as a `suite_check` family, independent of all
   of the above.

---

## E.9 Open questions

1. **Who labels, and at what rate.** Every item here assumes attorney time exists to produce
   ground truth. If it does not, the realistic design is a much smaller golden set that is
   maintained carefully rather than a broad set maintained badly, and E.6's tiering becomes the
   primary mechanism rather than a convenience.
2. **Whether native types survive contact with Harvey.** E.1's scoring plan rests on types that
   were inferred from prompt wording and never confirmed. A wrong type produces a confidently
   wrong `match_mode`. The first real run should be treated as a type audit as much as an
   evaluation.
3. **Whether `passed` should survive at all.** A system whose stated posture is findings not
   verdicts stores a verdict here. It may be right to keep it as a convenience over the computed
   comparison, or it may be that the honest shape is a recorded comparison plus a separate human
   disposition. Worth deciding deliberately rather than by inheritance.
