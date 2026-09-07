# Evaluation and Revision

Use this reference when reviewing a completed table, comparing versions, or deciding whether a prompt needs revision. Record findings in `assets/evaluation-log-template.md` (or the `.csv` version for spreadsheet work).

## Inspect the full output surface

Where available, review separately:

- Normalized answer
- Reasoning
- Supporting evidence or quotation
- Citation or source location
- Confidence or exception flag

A correct conclusion with noncompliant output is a formatting failure. A compliant answer supported by incorrect reasoning may expose a latent reliability problem.

## Build a representative test set

Cover the dimensions that can change prompt behavior:

- Each material document type
- Single-subject and multi-subject files
- Signed, partially signed, unsigned, filed, and government-issued documents
- Amendments, restatements, compilations, and attachments
- Documents that expressly address the issue
- Documents that are silent
- Documents that incorporate external terms
- Incomplete, illegible, or internally conflicting records
- Multiple records about the same underlying subject
- Upstream classifications with each relevant fallback state
- Multi-hop dependency chains and changed upstream results
- Conditional columns when the triggering condition is met and not met
- Locked and unlocked cells during selective reruns
- Grouped document sets with consistent, complementary, and conflicting evidence

Do not judge a general prompt only on the document that revealed the initial problem. The coverage checklist in the evaluation log template mirrors this list; an unticked dimension is open risk, not a pass.

## Failure taxonomy

Classify failures before revising:

| Failure class | Typical symptom | Likely correction |
| --- | --- | --- |
| Scope leakage | Parent, owner, counterparty, DBA, or referenced entity appears as the subject | Make principal-subject logic self-contained and add exclusions |
| Concept conflation | Authorized, issued, and owned interests are merged | Split the schema or define precise boundaries |
| Document-type error | Delivery date treated as expiry; filing date treated as formation date | Add document-specific routing and date hierarchy |
| Temporal-status error | Initial or historical leaders presented as current | Add current, historical, and change-state distinctions |
| Evidence overstatement | Unsigned consent described as approved action | Add execution-status dependency and nonoperative language |
| Holder or direction error | A right is assigned to the wrong party or relationship is reversed | Require exact names and define direction from the current document |
| Silence/uncertainty error | Silent document returns `Unable to determine` | Give `Not addressed` (or `Not stated` for Date, Number, Currency, and Duration columns) precedence when no relevant language exists |
| Vocabulary drift | Cell returns `N/A`, `None`, `Unclear`, or another synonym for a configured fallback | Restate the controlled vocabulary in the output contract; for Classify columns, confirm the configured options match |
| Applicability error | Status certificate produces governance analysis | Add document-type applicability rules or conditional execution |
| Dependency-routing error | A downstream column ignores or misuses an upstream classification | Tighten the `@` reference, applicable states, and fallback routing |
| Cascade error | An upstream error propagates plausible but incorrect downstream answers | Improve the upstream contract and require downstream confirmation against the review unit |
| Stale-dependent error | An upstream cell changes but dependent results reflect the old value | Rerun downstream dependents in dependency order and record the rerun scope |
| Grouped-source error | A grouped answer merges conflicting documents or obscures which document supports a fact | Define consolidation, conflict, and source-attribution behavior for the review unit |
| Aggregation error | Multi-entity compilation collapsed into one misleading state | Add a multiple-subject state and use a detail column |
| Output leakage | Citations, section numbers, reasoning, or clause text appear in the answer | Tighten the output contract and add native validation if available |
| Verbosity | Useful extraction becomes difficult to scan | Add labels, templates, item caps, and word limits |

## Evaluation log

Record at least:

| Test document | Column | Prompt version | Actual answer | Evidence relied on | Expected behavior | Failure class | Revision | Result after rerun |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Expected behavior can be a classification, a structural requirement, or an attorney-approved reference answer. Do not require exact prose matching when several concise answers would be equally correct. Record passes as well as failures, so a later reader can tell "tested and correct" from "not tested."

## Revision discipline

1. Confirm the source evidence before changing the prompt.
2. Determine whether the error is substantive, evidentiary, or merely formatting.
3. Revise the rule that explains the class of failure.
4. Preserve correct classifications already produced by the prompt.
5. Test the revised prompt on the failing document and neighboring document types.
6. Rerun only the changed column and downstream dependents when possible.
7. Record regressions rather than silently accepting them.

Selective reruns and cell locks preserve reviewed work but do not replace dependency-aware rerun planning. After any upstream change, confirm that each dependent result reflects the current upstream value; platform-adaptation.md records which platforms refresh dependents automatically and which do not. Keep the evaluation log outside the table.

Do not add a special rule for one named document when a general legal or document-type distinction explains the issue.

## Human validation boundary

Document-level extraction can surface conflicts without resolving them. Flag for attorney review when the task requires determining:

- Which document is operative or controlling
- Whether an entity or authority defect exists
- Whether transaction approval or consent is required
- Whether approval has been properly obtained
- The legal or deal consequence of a discrepancy
- Materiality, enforceability, or legal risk

The evaluation should distinguish a prompt defect from a genuine source-document conflict. A grouped review unit can surface differences among the documents in the group; it does not establish which document is operative or controlling. Grouping limits are in platform-adaptation.md.
