# Review Table Design Workflow

Use this workflow when creating a table, restructuring broad starter prompts, or producing a maintained prompt inventory. Platform capability facts live in [platform-adaptation.md](platform-adaptation.md); this file refers to them rather than restating them.

## 1. Establish the review unit and purpose

Identify:

- What one row represents: document, agreement, entity, property, person, or another unit
- Whether one row contains a single document or a grouped review unit
- The legal or business review objective
- Expected document types
- Intended reviewers and downstream use
- Whether analysis is limited to the current document or may use other rows or shared documents
- Platform constraints: column types, prompt limits, dependency support, and rerun behavior (for Harvey, see platform-adaptation.md)

Do not silently convert a document-level extraction table into an entity-level or portfolio-level legal analysis. The two have different evidence standards, and a reviewer who expects one will misread the other.

## 2. Inventory the starter schema

For each existing column, record:

- Name
- Current prompt
- Intended purpose
- Response type
- Concepts combined in the field
- Inputs or upstream facts it implicitly depends on

Identify overloaded fields. Split a field when its components have materially different subjects, evidence standards, fallback states, output shapes, or review consequences.

Start the prompt inventory now using `assets/prompt-inventory-template.md`, recording each starter prompt as the column's original prompt so the before-and-after is preserved.

## 3. Propose a human-readable hierarchy

Order columns in the sequence a reviewer would naturally use. A common pattern is:

1. Document orientation
2. Parties or entity scope
3. Dates and status
4. Commercial, ownership, or governance substance
5. Actions, restrictions, and risk allocation
6. Official status or qualifications
7. Validation and human-review fields

Keep paired fields together: classification before detail, status before certificate detail, or general threshold before special threshold.

## 4. Define a specification for each column

Before writing prose, specify:

| Field | Question |
| --- | --- |
| Purpose | What decision or review need does this answer support? |
| Subject | Which entity, party, document, asset, or person is analyzed? |
| Response type | Classification, structured free response, date, number, Boolean, or quotation? |
| Included evidence | Which provisions or visible signals qualify? |
| Exclusions | Which plausible but incorrect evidence must be rejected? |
| Dependencies | Which prior classifications or shared parameters matter? |
| Fallbacks | How are silence (`Not addressed`, or `Not stated` for typed columns), inapplicability, incorporation, and ambiguity distinguished? |
| Output contract | Which labels, fields, format, and length are allowed? |

Use the specification to generate the prompt. Do not begin by adding generic legal detail.

## 5. Identify the dependency graph

Common upstream facts include document type, principal subject, governing entity, execution status, and document date. Common downstream extractions include substantive rights, obligations, approvals, and summaries.

If the platform supports references, identify stable upstream control fields and define an explicit sequence:

1. Orient and classify.
2. Extract conditionally.
3. Validate within the row.
4. Reconcile across related rows if the platform supports it.
5. Present exceptions for human review.

Record each dependency using the platform's exact reference syntax (for Harvey, `@Column Name`). Prefer Classify or other tightly constrained upstream fields over narrative outputs when the result controls downstream routing.

For each dependent column, specify:

- Which upstream results it receives
- Which upstream values make the issue applicable
- How upstream fallback or conflicting values affect the result
- Which facts must still be confirmed against the current review unit
- Which downstream columns require rerun if the upstream prompt or result changes

If the platform isolates columns, make each prompt self-contained and repeat the minimum necessary upstream logic. Record this duplication as a platform limitation rather than pretending the dependency does not exist.

Check platform-adaptation.md for whether conditional columns skip execution or only route output before describing any dependency design as an efficiency gain.

## 6. Draft and constrain outputs

Use the structures in [prompt-patterns.md](prompt-patterns.md) and calibrate density and length against [worked-examples.md](worked-examples.md). Choose labels that correspond to different review actions, not synonyms. Require only the detail the reviewer will use.

Select the native column type before drafting the prompt. When one field would require both a controlled state and variable detail, split it into a Classify column followed by a dependent Free Response column.

Where the platform offers table-level instructions, draft them as a separate artifact using the Table Instructions pattern in prompt-patterns.md, and store the text in the prompt inventory.

## 7. Test on a representative corpus

Include clean examples and edge cases across relevant document types, signed and unsigned records, compilations, amendments, incomplete files, and documents that are silent on key subjects. Follow [evaluation.md](evaluation.md) and record results in `assets/evaluation-log-template.md`.

Also test dependency behavior: upstream fallbacks, multi-hop chains, conditional non-applicability, changed upstream results, locked cells, and reruns of affected downstream columns. If documents are grouped, include consistent, complementary, and conflicting groups.

## 8. Revise by failure class

For each error:

1. Identify what the model returned.
2. Identify the evidence it relied on.
3. Determine whether the failure came from scope, classification, evidence, temporal status, fallback semantics, or output formatting.
4. Change the narrowest rule that addresses the class.
5. Rerun the affected column and any downstream dependents.

Avoid adding document-specific names or facts to a general prompt unless they are actual matter parameters.

Maintain prompt versions and expected behavior in the inventory and evaluation log rather than in the table. platform-adaptation.md records which platforms lack native versioning and automatic downstream refresh.

## 9. Maintain the inventory

Use `assets/prompt-inventory-template.md`. It keeps one record per column (native type, dependencies in both directions, purpose, original and current prompt, version, change log) plus a copy of the Table Instructions, which exports omit.

Keep human-review fields separate from AI extraction where useful, including reviewer, validation status, operative version confirmed, issue status, and deal consequence.
