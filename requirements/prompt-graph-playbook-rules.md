# prompt-graph — playbook rules

**Extends:** `prompt-graph-contract-review.md` (B)
**External sources**, both held outside this repository:
*Building Legal Playbooks: A Reference* — what a playbook should contain.
*Building Playbooks for Harvey: Architecture and Authoring Format* — what the platform can hold.
**Date:** 2026-09-18
**Status:** proposal. Nothing here is built.

**Revised 2026-09-18**, same day, after the architecture document landed. Three claims in the
first version were wrong and are corrected in place rather than quietly dropped: that the
unevaluable-gate defect was unnamed (G.5), that playbook dependencies cannot be recovered by a
parser (G.7), and that precedence conflicts resolve arbitrarily with nothing to detect them
(G.6). The second is the one that matters, because it changes what this would cost to build.

**Source material.** One MNDA playbook, 38 issues, audited 2026-09-18. Client-identifying content
is deliberately absent; the structural findings are what generalise.

---

## G.0 What is already covered

Not restated here. Doc B already proposes per-rule `owner`, `review_cadence_days` and
`last_reviewed_at`; `severity`; an `applicability` table with typed predicates; and
`rule_position` with `preferred|acceptable|unacceptable` stances, which is exactly the shape the
real playbook takes.

What follows is only what neither B nor the references have.

## G.1 The platform, and what it cannot hold

A Harvey rule has **five fields**: standard position, acceptable deviations, unacceptable
deviations, guidance, and an optional flag. That is the whole schema. The Word export renders
those five; it does not define them, so a heading added in Word maps back to nothing.

What the schema has no field for:

| Absent | Consequence |
| --- | --- |
| Rule-level applicability | Scope has to be written into the position text |
| Rule-to-rule dependency | A rule cannot reference another rule's outcome |
| Precedence | Nothing declares which of two conflicting rules governs |
| Stable identifier | Rules are keyed by name; a rename breaks every reference |
| Version, owner, effective date, provenance | No governance metadata at all |
| Absence remediation | The optional flag records *whether* a clause may be missing, not what to insert |
| Fallback ordering | Acceptable deviations are a set, not a sequence |
| Exhaustion state | No field for what happens when the fallback is also refused |

Conditions exist, but attached to workflow actions, gating whether an *action* fires rather than
whether a *rule* evaluates.

**The execution model matters as much as the schema.** One subagent per rule, dozens in parallel.
Each sees its own rule in full, the contract including exhibits, and a shared deal context (which
party, whose paper, how strict). No subagent sees another's text or conclusion. Shared inputs,
unshared conclusions. Edits land on per-rule branches and reconcile afterwards, with collisions
escalated to a lead agent.

Two consequences run through everything below. A rule cannot be conditioned on another rule's
outcome, because the fact never reaches the subagent. And rule count drives cost and latency
directly, so **120 thin rules are slower and dearer than 40 substantive ones covering the same
ground, and no better.**

### G.1.1 The conventions are a shadow schema

The authoring format answers the eight absences with six conventions, all of which live inside
Guidance in a fixed order:

```
Rule ID: <dotted.path>
<rationale>
Depends on: <rule ids + reason: trade-off | definition | aggregate exposure | ordering>
Precedence: <where two rules can collide>
On exhaustion: <what happens when the fallback is refused>
Source: <authority> · Reviewed: <date>
```

This is a second schema smuggled into a free-text field, and it is the most important fact for
everything that follows. Harvey cannot validate any of it: to the platform it is prose. The
conventions work only because people follow them, and as the authoring document says, a
convention applied inconsistently is worse than none.

## G.2 The measured shape of a real playbook

| | |
| --- | --- |
| Issues | 38 |
| With a standard position, Guidance and a Required flag | 38 |
| With acceptable deviations | 32 |
| With unacceptable deviations | **5** |
| With a structured escalation trigger | **3** |
| Marked required, giving no instruction for a missing provision | **9** |
| Rules gated on another rule's outcome | 4 |
| Risk provisions forming one exposure set, cross-referenced | 6, **none** |
| **Rules carrying any convention line** (ID, depends-on, exhaustion, source) | **0** |

The last row is the finding. Not one rule carries an identifier, a dependency, an exhaustion path
or an authority. The conventions are new and nothing in the existing estate follows them, which
is the normal state of a convention with no enforcement behind it.

Three counts taken directly against the authoring checklist:

| Checklist item | This playbook |
| --- | --- |
| No entry consisting only of "reasonable edits" | fails **14 times** |
| No Guidance sentence substituting prose for structure | fails **4 times** |
| Unacceptable field populated | fails on **33 of 38** rules |

## G.3 The job

The framing this document exists to make.

prompt-graph is not a second copy of the playbook and it is not a better authoring tool. **It is
the only place the shadow schema can be enforced.** Harvey holds five fields and treats the sixth
through eleventh as prose, so the conventions that make a playbook maintainable are unenforceable
at exactly the point they are written, and they decay silently.

Each of these is a check with no home today:

- A `Depends on:` pointing at a rule ID that does not exist.
- A rename that orphaned every reference to a rule, since rules are keyed by name.
- A precedence statement written into one rule and not its counterpart, invisible from the other
  side because a subagent reads one rule.
- A required rule with no absence remediation.
- Content duplicated across a parent rule and its children.

The first three are `DEAD_REFERENCE` in a new costume, which prompt-graph already emits for
`@Column`. The fourth is the `FALLBACK_NOT_STATED` shape. The fifth is near-duplicate detection,
which the consistency family already does by token overlap.

## G.4 The checker

The authoring checklist is 23 authoring-time items plus three post-entry. Sorted by what a
machine can settle:

| | Count | Examples |
| --- | --- | --- |
| **Mechanical** | 12 | absence remediation present where required; at least one acceptable deviation; no entry consisting only of "reasonable edits"; unacceptable field populated; Guidance carries a rule ID; precedence reciprocity; no parent/child duplication; document control block present; rule count proportionate |
| **Needs typed data** | 4 | no gap between the last acceptable and first unacceptable position; thresholds are numbers; workflow conditions observable; no applicability gated on another rule |
| **Judgment, left with a person** | 7 | named for the issue not the clause; one concept per rule; operative language supplied; no two rules producing contradictory edits |

Twelve of 23 are straight lint, close to `prompt_check`'s ratio today. The middle four are what
B's typed applicability and G.8's `evaluation_context` unlock. The last seven should stay
judgment, and saying so is the point: the tool reports, the lawyer decides.

## G.5 Unevaluable gates

**Corrected.** The first version claimed this defect had gone unnamed. It is named in the
architecture document, with three ranked remedies: consolidate, restate the condition against the
contract, or escalate instead. What remains true is that nothing *implements* it as a check.

The defect: four rules govern the terms of a provision the playbook rejects, each gated in prose
on whether client approval was obtained. The subagent reads the sentence, cannot determine whether
it is true, and proceeds anyway. Four rules can therefore negotiate the terms of a provision the
policy is to reject, on a matter where nobody was asked.

It is not a missing dependency. The dependency is declared, correctly, by a careful author. It is
that the declared dependency is **unevaluable by the runtime that will execute it**, detectable
only by something holding both the graph and a model of what a subagent can see.

Proposed: `GATE_UNEVALUABLE`. A rule declares a precondition resolving to neither the contract nor
the declared deal context. Evidence: the gate text, the referenced fact, the context keys
available. A finding, not a verdict, because some gates are correctly addressed to a human
reviewing afterwards and the system cannot tell which.

The remedy ordering belongs in the finding, since consolidation is right far more often than the
other two and also removes a subagent.

## G.6 The collision that does not collide

**Corrected.** The first version said conflicting rules resolve arbitrarily with nothing to detect
them. Too strong: collisions **are** detected. Two subagents editing the same text produce
conflicting tracked changes on their branches, and reconciliation escalates them to the lead
agent. That is real protection.

The refinement, and it is the case the audit actually found: **collision detection catches two
rules editing the same text, not one rule editing where another would have left it alone.**

A general rule requires changing *cause* to *direct* throughout. A specific rule lists accepting
*cause* as an authorised fallback. Only one of those produces an edit. There is no second branch
to conflict with, nothing escalates, and the outcome depends on which rule happened to fire.
**The contradiction is invisible precisely when one side's resolution is to do nothing**, which is
the ordinary shape of a general-versus-specific conflict.

Two such pairs in 38 rules, both a general terminology rule against a specific fallback.

### G.6.1 The silent cluster

Six consecutive issues are Limitation of Liability, Recipient's Liability for Representatives,
Indemnification, Disclosing Party's Liability, Injunctive Relief and Legal Expenses. One exposure
set, no cross-references. Indemnification's authorised fallback *is* prevailing-party legal
expenses, and Legal Expenses is a separate issue two rules down: one decision recorded as two,
each decided by an agent that cannot see the other.

Neither produces a collision, because they touch different text. Nothing in any of the six
announces itself. The `aggregate exposure` dependency type exists for exactly this, and gets
recorded only if someone is asked.

## G.7 What the graph costs, revised

**Corrected.** The first version argued playbook edges cannot be parsed and must be elicited,
making the graph the most expensive artefact in the system. That was wrong, and the conventions
are why.

`Depends on: mnda.indemnity.ip (trade-off) · mnda.damages.consequential (aggregate exposure)` is a
machine-readable edge list with typed reasons, at a fixed position in a fixed field. A parser
recovers the graph from it the same way prompt-graph recovers 716 edges from `@Column` today.

What survives in weaker form: the *judgment* is still authored. A human decides that indemnity and
consequential damages trade off, and no parser reaches that. But the recording is mechanical once
the convention is followed, and the marginal cost per edge is one line of text written at the
moment the author already has the thought.

**The real cost moved.** Not elicitation but **adoption**: 0 of 38 rules carry a convention line.
The graph is cheap to extract and currently empty. That makes the enforcement job in G.3 the thing
that decides whether any of this works, which is a better problem than an elicitation programme.

## G.8 Schema delta

Additive, on top of B's migration. Ordering against the other outstanding proposals is unresolved.

```sql
-- Stable identity, which the platform lacks entirely (G.1)
ALTER TABLE column_def ADD COLUMN rule_ref TEXT;   -- 'mnda.liability.general_cap'

-- Typed, authored edges. Existing kinds stay; these are the legal ones.
-- dependency.kind gains: trade_off | definition | aggregate_exposure | ordering
ALTER TABLE dependency ADD COLUMN authority TEXT;  -- who asserted it, on what basis

-- Declared conflict handling (G.6)
CREATE TABLE rule_superiority (
    id          INTEGER PRIMARY KEY,
    winner_id   INTEGER NOT NULL REFERENCES column_def(id),
    loser_id    INTEGER NOT NULL REFERENCES column_def(id),
    scope       TEXT,                  -- NULL = general, else the context it is local to
    note        TEXT,
    declared_by TEXT NOT NULL,
    UNIQUE (winner_id, loser_id, scope)
);

-- What a subagent can actually see, so a gate can be checked against it (G.5)
CREATE TABLE evaluation_context (
    id        INTEGER PRIMARY KEY,
    matter_id INTEGER NOT NULL REFERENCES matter(id),
    key       TEXT NOT NULL,           -- 'acting_for', 'paper', 'posture'
    note      TEXT,
    UNIQUE (matter_id, key)
);

-- Ordered fallbacks and exhaustion, neither of which the platform has (G.1)
ALTER TABLE rule_position ADD COLUMN sequence       INTEGER;
ALTER TABLE rule_position ADD COLUMN available_when TEXT;
ALTER TABLE rule_position ADD COLUMN on_rejection   TEXT;
```

`rule_ref` is new in this revision and is the load-bearing addition. Harvey keys rules by name, so
a rename silently breaks every convention reference pointing at it. A stable id held here, mapped
to the current name, turns a rename from an incident into a finding.

`evaluation_context` encodes a claim about someone else's engine, taken from published material
that will change. That makes it exactly what specification freshness (doc F) should watch.

**Still absent, deliberately:** no overlay table, no layer stack, no evaluation-time composition.

## G.9 Build order

The reference leads its structure-at-scale part with overlays and precedence. The audited playbook
has one client, one contract type, one jurisdiction. Building the overlay engine first would be
building for an estate that does not exist.

1. **Parse the five fields and the Guidance conventions.** The conventions are the primary parse
   target, not the position fields: identity, dependencies, precedence, exhaustion and provenance
   all live inside Guidance.
2. **The 12 mechanical checks.** No new schema, findings on a real document immediately.
3. **Rule identity and rename detection**, which nothing else provides.
4. **Ordered fallbacks and absence remediation**, the two conventions with the most direct effect
   on what a review actually does.
5. **`GATE_UNEVALUABLE` and superiority**, needing `evaluation_context` and typed positions.
6. **Overlays**, when there is a second client.

Steps 1 to 3 are about a week and produce findings on day one, since the checklist already fails
14 times on "reasonable edits" alone.

**A pressure worth respecting throughout.** Because every rule costs a subagent, consolidation is
usually the right remedy and decomposition usually the wrong one. prompt-graph's normalising
instinct runs the other way and should be resisted: the parent-plus-four-children case costs five
subagents where one would do, *and* breaks the gate. "No content duplicated across a parent rule
and its children" belongs in the first tranche of checks, not as an afterthought.

## G.10 Open questions

1. **Where the positions came from.** The most consequential question about any playbook and the
   one no document answers. A position may be client policy, firm house view, or inferred from
   past signed agreements. A signed contract records what was accepted, not whether it was
   preferred, an authorised fallback, or a concession made under deadline pressure. Those look
   identical afterwards, and the distinction stops being survivable once a playbook clears matters
   automatically. The `Source:` convention is where this lives. Zero of 38 rules carry one.
2. **Whether the conventions get adopted.** Everything in G.3 and G.7 assumes authors write the
   `Depends on:` line. If they do not, prompt-graph is checking an empty graph. The honest test is
   whether playbook two, written after the authoring format exists, carries the conventions.
3. **Whether `evaluation_context` is maintainable.** It encodes a third party's architecture from
   published material. A stale declaration makes `GATE_UNEVALUABLE` produce confident nonsense in
   both directions.
4. **Whether the audited decomposition is a defect.** Four child rules duplicating content held in
   the parent's fallback reads as a synchronisation hazard, and the scale argument says it is also
   four unnecessary subagents. It may still be a deliberate workflow choice not visible in the
   document. The finding is that the relationship is unexpressed, which holds either way.
