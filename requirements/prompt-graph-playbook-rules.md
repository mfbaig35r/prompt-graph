# prompt-graph — playbook rules

**Extends:** `prompt-graph-contract-review.md` (B), `building-legal-playbooks-reference.md`
**Date:** 2026-09-18
**Status:** proposal. Nothing here is built.

Doc B asked whether the model extends to contract review and answered from first principles. The
reference doc set out what a playbook should contain. This is the delta between them, written
after auditing a real playbook, and it exists because the audit changed the answer in two places:
it produced a finding class neither document anticipated, and it inverted the build order the
reference implies.

**Source material.** One MNDA playbook, 38 issues, audited 2026-09-18. Client-identifying content
is deliberately absent from this document; the structural findings are what generalise.

---

## G.0 What is already covered

Not restated here. Doc B already proposes per-rule `owner`, `review_cadence_days` and
`last_reviewed_at`; `severity`; an `applicability` table with typed predicates and an `all|any`
mode; and `rule_position` with `preferred|acceptable|unacceptable` stances. Between them those
cover a large share of the reference doc's Appendix A, and the real playbook's shape (Standard
Position, Acceptable Positions, Unacceptable Positions) maps onto `rule_position` without
argument.

What follows is only what neither document has.

## G.1 The measured shape of a real playbook

| | |
| --- | --- |
| Issues | 38 |
| With a Standard Position, Guidance and a Required flag | 38 |
| With Acceptable Positions | 32 |
| With Unacceptable Positions | **5** |
| With a structured escalation trigger | **3** |
| Marked required, giving no instruction for a missing provision | **9** |
| Rules whose applicability is gated on another rule's outcome | 4 |
| Risk provisions forming one exposure set, cross-referenced | 6, **none** |
| Rules carrying an id, owner, version, effective date or authority | **0** |

Three numbers carry the argument.

**Five Unacceptable Positions against 32 Acceptable.** The boundary between what may be conceded
and what may not is stated for one issue in eight. Everywhere else the refusal is implied by
absence, which a reader infers and an evaluator cannot.

**Three structured escalation triggers against 38 issues.** Where they exist they are good: a
named action plus an explicit condition, which is the reference doc's "write the trigger, not the
vibe" done properly. The pattern is proven in the document itself and applied to under a tenth of
it. The other escalations live in Guidance prose.

**Zero rules carry governance metadata.** No id, owner, version, effective date, last-reviewed or
authority. The only date is in the filename, which is document-level, which the reference doc
specifically says tells a reader nothing about the rule in front of them.

## G.2 Four gap classes, and where each lands

The audit found four defect classes. Three have a home already; the fourth does not exist
anywhere and is the reason this document is worth writing.

| Gap | Shape | Status |
| --- | --- | --- |
| Required, with no instruction when the provision is absent | 9 rules | `FALLBACK_NOT_STATED` is the same shape and exists today |
| A value between the acceptable ceiling and the unacceptable floor | duration ladder accepts up to three years, refuses indefinite, is silent on four | DMN missing-rule detection; needs B's typed applicability |
| Two rules that both apply and disagree, with no tiebreak | 2 found, both a general terminology rule against a specific fallback | hit policy plus superiority; **not built** |
| **A gate on a fact the evaluator cannot see** | 4 rules | **no analogue anywhere; see G.3** |

The first is worth dwelling on because of how it fails. A contract that simply omits a required
provision produces no language to evaluate, so the review completes cleanly and the paper looks
clean. The absence is the finding, and absence is the one thing a clause-by-clause reading cannot
surface. `prompt_check` already reasons about this for silence states in prompts, which is the
same problem wearing different clothes.

## G.3 The finding class that is new: an unevaluable gate

Four rules in the playbook govern the terms of a provision the playbook's own policy is to
reject. Each carries, in prose, a gate of the form *this rule applies only once the fallback has
been approved by the client*.

The gate is correct. It is also unevaluable, and for a structural reason.

The execution engine evaluates rules in isolated parallel agents. They share deal context (side,
paper, posture) and do not share each other's conclusions; a lead agent reconciles afterwards. So
each of those four agents reads a gate referring to a fact that appears neither in the contract
nor in the context it receives. It cannot resolve the gate in either direction. Four rules can
therefore negotiate the terms of a provision the playbook rejects, on a matter where nobody was
asked.

**This is not a missing dependency.** The dependency is declared, correctly, by a careful author.
It is that the declared dependency is *unevaluable by the runtime that will execute it*, and that
is only detectable by a system that knows both the graph and what facts an evaluator can see.

Nothing has held both before. prompt-graph holds the graph and knows nothing about execution.
The engine executes and does not hold the graph. The check falls in the gap between them, which
is why it has gone unnamed.

Proposed: `GATE_UNEVALUABLE`. The rule declares a precondition that resolves to neither the
contract nor the declared evaluation context. Evidence: the gate text, the referenced fact, and
the context keys actually available. As always a finding, not a verdict: some gates are correctly
addressed to a human reviewing afterwards, and the system cannot tell which.

The same reasoning produces a companion check. Doc B's prose fixes for G.2's tiebreak gap work by
enumerating exceptions inside the general rule, which an isolated agent *can* apply because the
exception sits in its own text. That is sound, and it costs a pair of cross-references per
exception with nothing enforcing that the pair stays matched. Delete one side and the other still
names it. That is `DEAD_REFERENCE`, which prompt-graph already emits for `@Column`, pointed at a
new kind of edge.

## G.4 The silent version of the same failure

Six consecutive issues in the playbook are Limitation of Liability, Recipient's Liability for
Representatives, Indemnification, Disclosing Party's Liability, Injunctive Relief and Legal
Expenses. They form one exposure set. None references any other.

The sharpest instance: Indemnification's authorised fallback *is* prevailing-party legal expenses,
and Legal Expenses is a separate issue two rules down. Those two are one decision recorded as two,
and under parallel evaluation each is decided by an agent that cannot see the other.

This is G.3's failure with the volume off. The non-solicit gate at least announces itself in
prose, so an auditor reading carefully will find it. Here nothing in any of the six texts points
anywhere, so there is no sentence to notice. The reference doc's `aggregate_exposure` edge type
exists precisely for this, and the only way it gets recorded is if someone is asked for it.

## G.5 What the graph costs here

prompt-graph's 716 edges cost nothing: they are parsed out of `@Column` references already present
in prompt text. The parser is the author.

Playbook edges cannot be recovered that way. *Conceding here is acceptable only if that holds* is
not written in any document; it is held by the person who set the policy. Of the edges the audit
identified, the four gate edges were recoverable from prose (they were typed out four times), and
the six-provision exposure cluster was recoverable only by knowing what liability provisions do.
No parser reaches the second kind.

**Consequence for the build.** The graph stops being a free by-product and becomes the most
expensive artefact in the system, elicited rather than extracted. That inverts the economics: for
review tables the graph is cheap and evaluation is expensive, so evaluation is the bottleneck. For
playbooks both are expensive, and the graph cannot be deferred, because risk-based regression
selection depends on it.

It also changes the epistemics. A parsed edge is a discovered fact. An elicited edge is an
asserted judgment, and a wrong one is a legal error rather than a parse error. Edges therefore
need `declared_by` and an authority, which `dependency.declared_by` half-provides today.

## G.6 Schema delta

Additive, on top of B's migration. Ordering against the other outstanding proposals is unresolved;
this is migration 4, 5, 6 or 7.

```sql
-- Declared conflict handling (reference doc Part 3; G.2 row 3)
ALTER TABLE column_def ADD COLUMN hit_policy TEXT
    CHECK (hit_policy IN ('unique','any','priority','collect') OR hit_policy IS NULL);

CREATE TABLE rule_superiority (         -- which rule wins where two apply
    id          INTEGER PRIMARY KEY,
    winner_id   INTEGER NOT NULL REFERENCES column_def(id),
    loser_id    INTEGER NOT NULL REFERENCES column_def(id),
    scope       TEXT,                   -- NULL = general, else the context it is local to
    note        TEXT,
    declared_by TEXT NOT NULL,
    UNIQUE (winner_id, loser_id, scope)
);

-- Typed, authored edges (G.5). Existing kinds stay; these are the legal ones.
-- dependency.kind gains: trade_off | definition | aggregate_exposure | ordering
ALTER TABLE dependency ADD COLUMN authority TEXT;   -- who asserted it, on what basis

-- What an evaluator can actually see, so a gate can be checked against it (G.3)
CREATE TABLE evaluation_context (
    id          INTEGER PRIMARY KEY,
    matter_id   INTEGER NOT NULL REFERENCES matter(id),
    key         TEXT NOT NULL,          -- 'acting_for', 'paper', 'posture'
    note        TEXT,
    UNIQUE (matter_id, key)
);

-- Ordered fallbacks, which the playbook names but has no field for (G.7)
ALTER TABLE rule_position ADD COLUMN sequence       INTEGER;
ALTER TABLE rule_position ADD COLUMN available_when TEXT;
ALTER TABLE rule_position ADD COLUMN on_rejection   TEXT;
```

`evaluation_context` is the smallest thing that makes `GATE_UNEVALUABLE` computable: a declared
list of what the runtime supplies. It is a claim about the engine, so it will go stale when the
engine changes, which makes it exactly the kind of thing specification freshness (doc F) should
watch.

**Note what is absent.** No overlay table, no layer stack, no evaluation-time composition. That is
deliberate; see G.7.

## G.7 Build order, and why not overlays

The reference doc leads Part 3 with overlays and precedence, and from that document alone they
look like the first thing to build. The audited playbook says otherwise: one client, one contract
type, one jurisdiction, no layers. Building the overlay engine first would be building for an
estate that does not exist.

What the real playbook needs, in order:

1. **Gate edges**, so the parent-to-children relationship is declared once instead of typed into
   four Guidance fields. This also removes the duplication where the same four positions appear
   both inlined in the parent's fallback and decomposed in the children.
2. **Ordered fallbacks.** The document refers to "the Fallback Position" by name in five rules and
   has no such field, so fallbacks have been folded into Acceptable Positions. The vocabulary is
   ahead of the template.
3. **Absence handling on every required rule**, with the remediation language stored rather than
   improvised. Nine rules currently require a provision and say nothing about its absence, which
   means language gets drafted on the fly into an outbound redline, approved by nobody.
4. **Escalation triggers on the other 35**, following the pattern the document already proves on
   three.
5. **Hit policy and superiority**, which is where the two tiebreak conflicts get resolved
   structurally rather than in prose.
6. **Overlays**, when there is a second client.

Steps 1 to 4 need no new engine and mostly no new schema. They are authoring discipline that a
check can enforce, which is the cheapest kind of improvement available here.

## G.8 Open questions

1. **Where the positions came from.** This is the most consequential question about the playbook
   and the document cannot answer it. A position may be client policy, firm house view, or
   inferred from past signed agreements. A signed contract records what was accepted, not whether
   it was preferred, an authorised fallback, or a concession made under deadline pressure. Those
   look identical afterwards. The distinction was survivable when a lawyer read the playbook and
   applied judgment; it is less so when the playbook clears matters automatically. `provenance`
   and `requirement_source` are the places this would live, and every rule audited had neither.
2. **Whether `evaluation_context` is maintainable.** It encodes a claim about someone else's
   engine, sourced from published engineering material that will change. A stale context
   declaration would make `GATE_UNEVALUABLE` produce confident nonsense in both directions.
3. **Whether the decomposition found in the audit is a defect.** Four child rules duplicating
   content held in the parent's fallback reads as a synchronisation hazard, and may equally be a
   deliberate workflow choice not visible in the document. The finding is that the relationship is
   unexpressed, which holds either way. Confirm with the author before calling it an error, which
   is the general posture: the system reports what it sees and the judgment stays with a person.
