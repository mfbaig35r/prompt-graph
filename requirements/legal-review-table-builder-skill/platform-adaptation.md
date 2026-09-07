# Platform Adaptation

Use this reference to translate the general workflow into the capabilities of the target product. The Harvey section is the single source for Harvey capability facts in this skill; workflow.md, prompt-patterns.md, and evaluation.md point here rather than restating them. When Harvey changes, update this file only.

## First determine the execution model

Ask or inspect whether the platform supports:

- Cross-column references
- Dependency ordering
- Conditional execution
- Shared or table-level instructions
- Named variables or reusable prompt components
- Classification and structured response types
- Native output validation
- Reasoning and evidence fields separate from the answer
- Selective reruns and prompt versioning
- Cross-row or grouped analysis
- Prompt or query character limits

Do not write prompts that depend on a capability the platform does not provide.

## When columns are independent

Make each column self-contained enough to identify its principal subject, document type where necessary, evidence standard, and fallback behavior. Repeat only the rules needed for that column.

Do not write `use the entity identified in the Entity Name column` unless the platform actually passes that value into the query.

Shared instructions can reduce duplication, but verify that they are supplied to every column and understand whether column instructions override them. Keep critical scope or evidence rules in the column prompt until propagation is confirmed through testing.

## When references and dependencies are supported

Prefer a staged design:

1. **Orientation:** principal subject, document type, dates, execution or filing status.
2. **Conditional extraction:** substantive columns receive upstream values and run only when applicable.
3. **Validation:** compare outputs for internal inconsistencies.
4. **Reconciliation:** group related documents and surface conflicts when the platform supports cross-document or cross-row analysis.
5. **Human review:** present normalized evidence and exceptions.

Use explicit references only in the syntax supported by the platform. Define what happens when an upstream value is unavailable or changes after rerun. Prefer controlled, low-entropy upstream values for routing; do not make a long narrative answer the control plane for many later columns, because small wording changes upstream then alter every dependent result.

## Harvey Review Tables

**Last verified: 2026-09**, against Harvey product clarification and UI behavior. Before relying on an item below, re-verify it against the current UI when a material product change is plausible, and update this date when you do.

### Confirmed capabilities

- Reference an earlier column with `@Column Name`. Harvey sequences referenced columns before dependent columns.
- Chain dependencies across multiple columns, such as orientation → classification → detail → validation.
- Use conditional follow-up logic. A later column can inspect an upstream result and return a blank or configured fallback when the condition is not met.
- Use Table Instructions for corpus-wide matter context, entity lists, naming conventions, and shared rules. They apply to every new column, cannot be scoped to only one column, and are not included in exports.
- Use native column types: Classify, Date, Currency, Number, Duration, Verbatim, and Free Response.
- Rerun a single column or cell and lock verified cells so later work does not overwrite them.
- Group up to 25 related documents into one review unit. This permits document-group analysis within that unit.

### Partial capabilities and design consequences

- Conditional logic is output routing, not conditional execution. Every column runs against every row, so use it for applicability and consistency, never to claim execution-cost savings.
- Native types provide basic structural validation, but Harvey does not provide a single cell combining a controlled enum with structured free-text detail, or a full JSON-style schema. Split classification and detail into separate columns when both are needed.
- Table Instructions are the confirmed mechanism for reducing shared repetition. Do not assume separate named variables or reusable column-scoped prompt fragments exist without testing.
- Selective reruns do not invalidate or refresh downstream cells automatically, and there is no regression tracking.
- Grouping analyzes within one review unit only. It does not reconcile conflicts across separate rows and does not establish which document in the group is operative or controlling.

### Not currently available

- True skip-execution for irrelevant columns
- Native prompt/evaluation versioning, run comparison, or regression detection
- Cross-row grouped conflict review, such as reconciling inconsistent entity names or formation dates across separate rows

### Harvey design defaults

- Build an explicit dependency graph before drafting prompts. Put stable orientation and classification columns before dependent extraction.
- In a dependent prompt, name the upstream inputs at the start, for example `Use these established results: Document Type: @Document Type`.
- Use upstream results to maintain scope and consistency, but require the dependent column to confirm its substantive answer against the current review unit.
- Handle every upstream fallback state explicitly. Do not let `Unable to determine` silently route to a positive substantive classification.
- Use Table Instructions for global rules (pattern in prompt-patterns.md, example in worked-examples.md), but keep decision thresholds, exclusions, and output contracts in their owning columns. Store the Table Instructions text in the prompt inventory because exports omit it.
- Choose the narrowest native type that fits the output. Use Classify for one controlled state and a paired Free Response column for variable detail.
- Keep each query below 10,000 characters. Target roughly 6,000 characters or fewer when practical to leave room for revision.
- Require clean answers without citation artifacts when evidence and citations are available elsewhere in the interface or export.
- After changing an upstream prompt or result, rerun downstream dependents in dependency order. Lock verified cells only when preserving them is logically safe, which usually means the cell has no changed upstream input.
- For grouped documents, define whether the answer should consolidate consistent evidence, identify document-specific differences, or return `Unable to determine` when the group conflicts. Do not imply that grouping establishes which document controls.

## Claude and ChatGPT

The core skill is portable. Adapt file handling and artifact creation to the tools available in the current environment.

- If the model can read a workbook directly, inspect the complete prompt inventory and representative result rows.
- If it cannot, request a CSV or Markdown export containing column names, prompts, answers, reasoning, and evidence.
- Keep `SKILL.md`, `references/`, and `assets/` together so relative links remain usable.
- Do not assume that a chat model's general context-sharing behavior matches a Review Table product's column execution model.

## Output portability

Raw Markdown prompts are the safest default for handoff. Avoid product-specific wrappers unless requested. Preserve configured option labels exactly and identify any syntax that must be adapted before import into another platform.
