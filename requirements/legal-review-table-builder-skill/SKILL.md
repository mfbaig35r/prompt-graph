---
name: legal-review-table-builder
description: Design, draft, test, and refine column schemas and prompts for legal document review tables, especially due-diligence extraction tables in Harvey Review Tables. Use this whenever the user mentions Harvey, a review table, review grid, or diligence table; column prompts, @Column references, Table Instructions, Classify options, or a prompt inventory; or wants to turn a list of extraction questions into columns, diagnose a completed table's outputs, or revise prompts after a test run. Use it even when the user pastes a plain list of legal questions or a spreadsheet export without calling it a table. Do not use for substantive legal advice unrelated to review-table design.
---

# Legal Review Table Builder

Build review tables as structured extraction systems, not collections of loosely related questions. The deliverable is a reliable review candidate for an attorney: document-level evidence that is easy to extract, normalize, compare, and validate, with legal judgment left visibly to the human.

## Choose the operating mode

- **Design:** Create or reorganize a column schema from a diligence objective, document set, or simplistic starter table. Read [references/workflow.md](references/workflow.md), then [references/prompt-patterns.md](references/prompt-patterns.md), because design almost always ends in drafting.
- **Draft:** Write one or more platform-ready column prompts. Read [references/prompt-patterns.md](references/prompt-patterns.md) and calibrate against [references/worked-examples.md](references/worked-examples.md).
- **Evaluate:** Inspect a completed run, identify systematic failures, and recommend revisions. Read [references/evaluation.md](references/evaluation.md).
- **Revise:** Narrowly fix demonstrated failure classes while preserving correct behavior. Read both the prompt-pattern and evaluation references.
- **Adapt:** Account for Harvey, ChatGPT, Claude, or another platform's limits and dependency model. Read [references/platform-adaptation.md](references/platform-adaptation.md). It is the single source for Harvey capability facts; the other references point to it rather than restating them.

For any Harvey work, read platform-adaptation.md before designing a column sequence. The dependency, rerun, and grouping model shapes every downstream decision.

When the user provides a workbook, prompt inventory, export, or source documents, inspect the relevant artifact before redesigning the table. Do not infer its contents from a filename or a screenshot when the underlying file is available.

## Bundled resources

- `references/` — the mode-specific guidance above.
- `assets/prompt-inventory-template.md` — the maintained record of every column, its prompt versions, and its dependencies. Use it whenever you deliver a full suite or revise more than one column, so inventories look the same from project to project.
- `assets/evaluation-log-template.md` (and `.csv` for spreadsheet import) — the test-set coverage checklist and per-failure log. Use it whenever you evaluate a run.

## Core design principles

### Treat every column as a data contract

Define the column's purpose, subject, evidence boundary, response type, valid states, fallback semantics, and output format. A clear legal question is not necessarily a complete extraction specification.

### Design the schema before expanding prompts

Split fields that combine concepts with different evidence or review consequences. Common examples include:

- Formation date versus principal document date
- Authorized capital versus issued interests versus ownership
- Named leaders versus governing-body composition
- Ordinary approval thresholds versus protective or supermajority rights
- Preemptive rights versus restrictions on transfers of existing equity
- Entity standing versus details of the certificate reporting it

Use these as diagnostic examples, not mandatory columns for every project.

### Make scope explicit

Identify the principal document, entity, agreement, property, person, or other review subject. Exclude parents, owners, affiliates, counterparties, exhibits, trade names, and referenced documents unless the column is intended to report them. Most scope failures come from a nearby entity that is mentioned prominently but is not the subject.

Use upstream results when the platform explicitly supports references and execution dependencies. Prefer stable orientation fields, such as document type, principal subject, and execution status, as inputs to later extraction and synthesis columns. If references are unavailable, repeat only the minimum scope logic needed to keep each column reliable.

Treat a referenced result as an input, not as conclusive evidence. A downstream column should use the upstream result to maintain scope and routing, then confirm its own substantive answer against the current review unit. Define how downstream logic handles every upstream fallback state, so that `Unable to determine` upstream never silently becomes a positive finding downstream.

### Separate document content from completion evidence

Do not describe an unsigned, unfiled, unadopted, or uncertified document as having completed an action unless visible evidence supports that conclusion. Use language such as `unsigned`, `purports to`, `would`, or `proposed` where appropriate.

Do not decide ultimate validity, enforceability, operative status, defect, transaction approval, or deal consequence unless the user expressly requests that legal analysis and provides the necessary inputs. The human validation boundary in evaluation.md lists the determinations to leave for attorney review.

### Give absence and uncertainty distinct meanings

Use one controlled vocabulary of fallback states across the whole table:

- `Not addressed`: the document is silent on the subject.
- `Not stated`: the Date, Number, Currency, or Duration value the column asks for does not appear in the document. This is the typed-column counterpart of `Not addressed`; use it only in those column types.
- `Not applicable`: the subject has no meaningful application to this document type.
- `Incorporated terms`: another document supplies the terms, but they are not reproduced in the current review unit.
- `Unable to determine`: relevant evidence exists but is illegible, incomplete, conflicting, or genuinely ambiguous.

These states drive different reviewer actions. Silence sends the attorney to check whether another document should cover the point; inapplicability needs no follow-up; incorporation sends them to locate the other document; genuine ambiguity sends them to the source. Collapsing two states hides which action is needed.

Do not use `Unable to determine` merely because the document is silent, and do not introduce synonyms such as `None`, `N/A`, `Unclear`, or `Silent`. In a Free Response column, `Unable to determine` and `Incorporated terms` may carry a short qualifier after an em dash (`Unable to determine — signature page missing`). In a Classify column, return the exact configured option only.

### Use document type as routing logic

Dates, execution evidence, corporate actions, status, and other fields may require different rules for different document types. Encode the smallest useful hierarchy rather than asking for the most prominent text on the page.

Where dependencies are supported, implement this routing as a visible column sequence: orientation and controlled classifications first, conditional detail second, and synthesis or validation last. Do not simulate a dependency by asking a later column to rediscover an upstream result unless testing shows the reference is unreliable.

### Normalize the interface

Use controlled labels, exact names, concise response templates, word limits, and deterministic fallbacks when the output will be filtered or compared. Keep the normalized answer separate from reasoning, evidence, quotations, and citations.

## Working behavior

- Preserve the user's chosen platform, schema, column type, and configured options.
- For Harvey Review Tables, use `@Column Name` references and explicit dependency chains when they improve scope, routing, or consistency.
- Put corpus-wide matter context, defined entities, naming conventions, and shared rules in Table Instructions when available. Keep column-specific decision rules in the relevant column prompt.
- Ask questions only when an unresolved choice would materially change the table. Otherwise state reasonable assumptions and proceed.
- If the user wants prompts one at a time, return the next prompt only and preserve the agreed sequence.
- Present copyable prompts as raw Markdown in fenced code blocks unless the target interface requires another format. For Harvey prompts, follow the construction standard in [references/prompt-patterns.md](references/prompt-patterns.md).
- Keep prompt length below the target platform limit. Remove repetition before removing rules that prevent observed errors.
- Prefer exact party and entity names over inferred roles when identity matters.
- Do not infer from filenames, common practice, or documents outside the current review unit unless the workflow expressly permits cross-document analysis.
- When evaluating outputs, diagnose the failure class before rewriting the prompt.
- Revise the narrowest rule that explains the failure; do not optimize around a single example at the expense of the broader document set.
- Keep human validation visible. The desired output is a reliable review candidate, not an unqualified final legal conclusion.

## Expected deliverables

Provide only what the user requests, choosing among:

- A logically ordered column hierarchy
- A dependency map showing which columns reference which upstream results
- A short attorney-readable purpose for each column
- Recommended native column types and configured classification options
- Platform-ready prompts
- Table-level shared instructions
- A versioned prompt inventory, using `assets/prompt-inventory-template.md`
- An evaluation report linking failed outputs to prompt causes, using `assets/evaluation-log-template.md`
- Revised prompts with concise enhancement notes
- A rerun plan limited to affected columns and downstream dependents
- Product feedback describing platform limitations exposed by the build

When producing a full suite, keep column names, purposes, prompt versions, enhancement notes, and current prompts in one maintainable inventory.
