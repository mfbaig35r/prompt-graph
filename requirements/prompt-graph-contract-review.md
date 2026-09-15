# prompt-graph — contract-review extension

**Extends:** `prompt-graph-mcp-requirements.md`, `prompt-graph-addendum-a.md`
**Date:** 2026-09-15
**Status:** proposal. Nothing here is built. Migration 3 below has been applied to a copy of a
real database and verified; it has not been added to `MIGRATIONS`.

The server was built for M&A diligence review tables. This records what changes if the same
engine also has to carry **contract-review playbooks**: modular rule sets applied to a
contract to produce clause mapping, deviations, and recommendations.

The conclusion is that the governance machinery transfers almost intact and the legal content
model does not. This document separates those two so the second does not quietly contaminate
the first.

---

## B.0 Why this is the same system

The transfer works because prompt-graph never executes anything. It stores, versions, links,
and compares. The only platform-facing code is `harvey.py`, 110 lines, and it exists solely to
poll vault document counts for freshness.

| prompt-graph | contract-review playbook |
| --- | --- |
| `column_def` | one playbook rule |
| `review_table` + `review_unit` | one playbook module + what it applies to |
| `prompt_version` | versioned rule text with a change note and the class it addressed |
| `dependency` + `impact_of_change` | what needs re-validation when a module changes |
| `run_snapshot` | the drift baseline |
| `eval_result` | one golden-set row |
| `run_compare` | did fixing rule 7 break rules 1 through 6 |
| `staleness_report` | which rules need re-running, in order |
| `shared_parameter` + bindings | definitions shared across modules |
| `standard` | house conventions for recommendations |

Two of these are worth stating plainly because they answer questions the domain asks and has
no other way to answer.

**`run_snapshot` is the drift baseline.** It pins `(run, column, prompt_version_id,
instructions_version_id)`. When an output changes, that pin is what distinguishes *we edited
the rule* from *the model changed underneath us*. Without it, drift is anecdote. This is
already built and it is the single most valuable thing prompt-graph brings to the domain.

**`column_def.concept` plus the consistency checks answer the modularity objection.**
`CONCEPT_NAME_VARIANT` and `CONCEPT_DIVERGENT_RULES` fire when the same concept is asked under
different names, or resolved under different rules, across tables. That is exactly the failure
mode of splitting one large playbook into six owned modules. The check exists and runs today.

Empirical support for modular decomposition: the 591-prompt corpus resolves into 24 modules,
261 intra-module reference edges, four stages (338 / 219 / 32 / 2), and **no dependency
cycles**. Modularity at this scale is observed, not assumed.

---

## B.1 Ownership and review cadence

### The problem

Governance is asked for at the clause and term level: who owns each rule, and when was it last
looked at. `provenance.actor` records who last *changed* something, which is a different
question from who is *accountable* for it. A module split across six owners without recorded
ownership relocates the coupling instead of removing it.

### Design

`owner`, `review_cadence_days`, `last_reviewed_at` on both `review_table` and `column_def`. A
NULL owner on a rule inherits the module's owner, so the common case costs one field per
module rather than one per rule.

Findings: `OWNER_UNASSIGNED`, `REVIEW_OVERDUE` (`last_reviewed_at` + cadence in the past).
Both belong in `table_readiness` under a new `governance` cause.

---

## B.2 Severity

### The problem

A deviation on a walk-away term and a deviation on a drafting preference are not the same
event, and an exception queue that cannot tell them apart is a list, not a queue. Columns
carry `role` (orientation, extraction, validation, reconciliation, human_review), which
describes what the rule *does*, not what breaking it *costs*.

### Design

`column_def.severity` in `{blocking, material, advisory}`, nullable.

Severity is a property of the rule, not of the result, so it does not belong on `eval_result`.
The weight of a missed rule is then derivable: join the failed result to its column.

New cross-module check: `CONCEPT_SEVERITY_DIVERGENT`, the same concept graded differently in
two modules. This extends the existing concept checks and is the governance question modular
playbooks actually raise.

---

## B.3 Applicability

### The problem

This is the real gap. `stage` and `position` order modules; nothing declares *when a module
applies*. Orchestration cannot route without that, and routing is what makes modularity
tolerable to the person who has to run it: more modules must not mean more clicks.

### Design

Multiple predicates per subject, combined by `applicability_mode` in `{all, any}` on the
subject itself, defaulting to `all`.

Each predicate carries an authoritative human-readable `expression` and, where it can be
evaluated, a structured basis: a `shared_parameter` or a classifier `column_def`, an operator,
and an operand.

**`basis_type = 'manual'` is a first-class outcome, not a modelling failure.** Some predicates
will never be machine-evaluable ("applies when counsel determines the vendor processes PHI").
Storing them as manual and reporting `APPLICABILITY_MANUAL` is consistent with findings, not
verdicts: the server records that a module cannot be routed automatically. It does not refuse
to store the module, and it does not pretend to route it.

Findings: `APPLICABILITY_MISSING`, `APPLICABILITY_MANUAL`.

### The addendum case

An addendum is a conditional workflow artifact, not a rule inside the main playbook. It falls
out of applicability plus severity without new machinery: a classifier column detects the
triggering fact, an applicability predicate on the addendum module reads it, and the module's
rules carry `blocking` severity because a missing required addendum stops the deal.

Note that `review_unit` already carries this shape. The corpus defines Contracts Core's unit
as "one agreement family, a base agreement together with every amendment, restatement,
statement of work, order form, and side letter produced for it." Contract plus addenda is the
same object.

**Unvalidated.** The vendor has reportedly said there is no clean in-playbook solution and
suggested flags at the playbook stage followed by a separate workflow. That matches this
design, but it is a vendor suggestion that nobody has tested. Treat it as an open test item.

---

## B.4 Rule positions

### The problem

A review-table column asks a question and types the answer. A playbook rule carries a
preferred position, an acceptable fallback, an unacceptable floor, and often suggested
language. `configured_options` on a Classify column can hold a verdict; it cannot hold a
negotiation ladder.

### Design

`rule_position` rows hang off **`prompt_version`, not `column_def`**.

This is the load-bearing choice in the whole document. `run_snapshot` already pins
`prompt_version_id` per run, so attaching positions to the version means every recorded run
captures the fallback ladder in force at the time, for free, with no change to the run
machinery. Attaching them to the column would require a parallel snapshot table and would
still resolve incorrectly on a rerun of an older version.

`redline_language` is stored **verbatim as supplied**. The server does not draft or rewrite
prompt text and this is not an exception to that rule; it is a field the caller fills.

Finding: `POSITIONS_MISSING`, a rule with no `preferred` position.

---

## B.5 Per-result facets

`run_coverage` is currently hand-ticked: a caller asserts which test-set dimensions a run
covered. `eval_result_dimension` tags each individual result with the dimensions it exercised,
which lets run coverage be **derived** from results rather than claimed alongside them.

This is an improvement to the existing design rather than a contract-review addition, and it
also absorbs a domain need cleanly: own paper versus counterparty paper is a coverage
dimension, not a column. The same playbook applied in both directions roughly doubles the
golden set, and that is a fact the coverage report should surface rather than a field on
`eval_result`.

Seeding those dimension rows is a `constants.py` change with no migration.

---

## B.6 Failure taxonomy

No schema change. `eval_result.failure_class` is free TEXT.

The 19 classes are extraction failures inherited from the skill. Contract review fails
differently: clause missed, deviation misgraded, wrong fallback recommended, obligation
hallucinated, addendum requirement not raised. The taxonomy needs a domain sibling; the
mechanism that consumes it (`failures_summary` grouping, `prompt_version.failure_class_addressed`,
`run_compare` regression detection) is unchanged.

---

## B.7 `modules_for`

The only genuinely new tool. Everything else is optional fields on `table_ingest`,
`column_revise`, and `table_readiness`.

`modules_for(matter, facts)` returns, given classifier output: which modules apply, which do
not and why, and which predicates could not be evaluated automatically and therefore need a
human. That last list is the honest part, and it is what stops orchestration from silently
under-routing.

---

## Migration 3

Additive only. Nothing in migrations 1 or 2 is altered.

```sql
-- Ownership and review cadence (B.1)
ALTER TABLE review_table ADD COLUMN owner               TEXT;
ALTER TABLE review_table ADD COLUMN review_cadence_days INTEGER;
ALTER TABLE review_table ADD COLUMN last_reviewed_at    TEXT;
ALTER TABLE column_def   ADD COLUMN owner               TEXT;   -- NULL inherits the module owner
ALTER TABLE column_def   ADD COLUMN review_cadence_days INTEGER;
ALTER TABLE column_def   ADD COLUMN last_reviewed_at    TEXT;

-- Severity (B.2)
ALTER TABLE column_def ADD COLUMN severity TEXT
    CHECK (severity IN ('blocking','material','advisory') OR severity IS NULL);

-- Applicability (B.3)
ALTER TABLE review_table ADD COLUMN applicability_mode TEXT NOT NULL DEFAULT 'all'
    CHECK (applicability_mode IN ('all','any'));
ALTER TABLE column_def   ADD COLUMN applicability_mode TEXT NOT NULL DEFAULT 'all'
    CHECK (applicability_mode IN ('all','any'));

CREATE TABLE applicability (
    id              INTEGER PRIMARY KEY,
    table_id        INTEGER REFERENCES review_table(id),
    column_id       INTEGER REFERENCES column_def(id),
    expression      TEXT NOT NULL,      -- authoritative, human-readable condition
    basis_type      TEXT NOT NULL CHECK (basis_type IN ('parameter','classifier_column','manual')),
    parameter_id    INTEGER REFERENCES shared_parameter(id),
    basis_column_id INTEGER REFERENCES column_def(id),
    operator        TEXT CHECK (operator IN ('equals','in','contains','present','absent')),
    operand         TEXT,               -- json scalar or list
    note            TEXT,
    created_at      TEXT NOT NULL,
    is_current      INTEGER NOT NULL DEFAULT 1,
    CHECK ((table_id IS NOT NULL) + (column_id IS NOT NULL) = 1),
    CHECK (
        (basis_type = 'parameter'         AND parameter_id    IS NOT NULL AND operator IS NOT NULL) OR
        (basis_type = 'classifier_column' AND basis_column_id IS NOT NULL AND operator IS NOT NULL) OR
        (basis_type = 'manual'            AND parameter_id IS NULL AND basis_column_id IS NULL)
    )
);
CREATE INDEX idx_applicability_table  ON applicability(table_id, is_current);
CREATE INDEX idx_applicability_column ON applicability(column_id, is_current);

-- Rule positions, versioned WITH the rule (B.4)
CREATE TABLE rule_position (
    id                INTEGER PRIMARY KEY,
    prompt_version_id INTEGER NOT NULL REFERENCES prompt_version(id),
    stance            TEXT NOT NULL CHECK (stance IN ('preferred','acceptable','unacceptable')),
    position          INTEGER NOT NULL,
    statement         TEXT NOT NULL,
    redline_language  TEXT,
    note              TEXT,
    UNIQUE (prompt_version_id, stance, position)
);
CREATE INDEX idx_rule_position_version ON rule_position(prompt_version_id);

-- Per-result facets (B.5)
CREATE TABLE eval_result_dimension (
    eval_result_id INTEGER NOT NULL REFERENCES eval_result(id),
    dimension_key  TEXT NOT NULL REFERENCES coverage_dimension(key),
    PRIMARY KEY (eval_result_id, dimension_key)
);
```

**Two nullable foreign keys, not a polymorphic `subject_id`.** The connection runs
`PRAGMA foreign_keys = ON`; a polymorphic reference silently opts out of enforcement. The
`(table_id IS NOT NULL) + (column_id IS NOT NULL) = 1` check costs one line and keeps
referential integrity real.

### Verification, 2026-09-15

Applied to a `.backup` copy of a real 24-module / 591-rule database:

- `PRAGMA integrity_check` → `ok`; `PRAGMA foreign_key_check` → clean.
- Row counts unchanged: 24 modules, 591 rules, 591 prompt versions, 261 edges.
- `applicability_mode NOT NULL DEFAULT 'all'` backfilled all 591 existing rows.
- `severity` NULL on all 591 existing rows.
- All four CHECK constraints reject violating rows (bad severity, both subjects set,
  `parameter` basis with no parameter, bad stance). Valid rows accepted.

---

## Platform constraint this design has to live inside

Verified against Harvey primary sources 2026-08-16, and it bounds what the governance layer
can promise.

The public API has **no workflow-execution endpoint, no job or run resource, no webhooks, and
no scheduler**. Thirty endpoints: Completion, Vault, History Export, Audit Logs, Client
Matters. Review Tables row results can be read; column definitions cannot. The Completion API
has no `response_format`, no JSON schema, no `temperature`, and no `seed`.

Three consequences.

1. **Reruns cannot be triggered from code.** The achievable shape is manual trigger, automated
   scoring: a person re-runs in the UI, the harness reads results and scores them against the
   golden set. That is most of the value, because the comparison is the expensive part. It is
   not CI/CD and should not be described as CI/CD.
2. **Structured output means typed columns, not a schema parameter.** Prompt-enforced
   structure in a typed review table is the available mechanism. Anything that reads as JSON
   schema from the API will not survive a technical review.
3. **Textual determinism is not available, so do not design for it.** With no `seed` and no
   `temperature`, the objective has to be *same input produces a substantively equivalent
   outcome within defined tolerances*. That is forced by the platform rather than chosen for
   elegance, which is the stronger way to argue it.

Rate limits are per organisation: Completion 20/min, Vault 10/min. Keep evaluation inside
Review Tables and read results out. Never reimplement a run through the Completion API, where
a 300-cell suite would consume fifteen minutes of an entire firm's budget.

---

## Deliberately not in this

- **No `paper_side` on `eval_result`.** Domain vocabulary in a general schema. Routed through
  `coverage_dimension` plus `eval_result_dimension` instead (B.5), no migration.
- **No exception-queue analogue to the memo layer.** `memo_outline → section → assertion →
  assertion_source` answers "can the suite support the diligence memo". The contract-review
  output is a redline plus an exception list plus required addenda. Same shape, different
  artifact. That is a design question, not a field, and it is not answered here.
- **No import path.** Unchanged from A.3.

---

## Open decisions

**1. One schema or two packages.** Everything above except `rule_position` is governance
metadata any ontology would want. Storing preferred / acceptable / unacceptable asserts that a
rule is a negotiation object, which an M&A extraction column is not and never will be. Either
one schema carries both ontologies with an empty child table on the diligence side, or a
shared governance core is split from two domain packages.

**Decided 2026-09-15: one schema.** A nullable child table costs nothing, and the split is
easier to justify later against two real users than to guess at now. Recorded in
`DECISIONS.md` under "Contract-review extension", with the signal that should trigger a
revisit.

**2. Default applicability reads as "always applies."** `applicability_mode` defaults to
`all`, and every existing rule has zero predicates, so "all of nothing" is vacuously true.
That is correct for the diligence corpus, which has no conditional routing. It means
`APPLICABILITY_MISSING` has to be a finding rather than an error, or a first run over the
corpus emits 615 complaints.

**3. Eval suite sizing is unresolved.** Top-N clauses versus every variation with multiple
examples each. This is a scoping decision that changes the cost of everything downstream and
it should be settled before any suite is built.

**4. The evaluation layer has never run.** As of 2026-09-15 the database holds 0 runs and 0
evaluation results. Ingest, lint, and the graph have been exercised on 591 real rules;
`run_record`, `eval_record`, `run_compare`, staleness, and coverage have only ever run against
the demo fixture and the test suite. A first live engagement would also be this layer's first
real use.
