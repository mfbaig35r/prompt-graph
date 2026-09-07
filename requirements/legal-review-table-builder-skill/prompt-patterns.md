# Prompt Patterns

Use these patterns as scaffolds. Adapt them to the document set, legal concept, and target platform. Do not copy every section into every prompt. For fully realized prompts built from these scaffolds, including a Table Instructions example, see [worked-examples.md](worked-examples.md).

## Harvey prompt construction standard

Use Markdown to separate instruction functions and make prompts maintainable. Do not assume Markdown formatting itself improves Harvey's legal reasoning. The substance of the scope, decision rules, fallbacks, and output contract controls the result.

### Canonical section order

Use the following order when the sections are relevant:

1. `## Established results` — only for actual `@Column Name` dependencies.
2. `## Task` — one direct statement of the required classification, extraction, or synthesis.
3. `## Scope` — the review subject, evidence boundary, included concepts, and important exclusions.
4. `## Options` or `## Response labels` — only when their definitions or exact labels must be stated in the prompt.
5. `## Classification rules`, `## Extraction rules`, or a concept-specific rules heading — the operative decision logic.
6. `## Fallback rules` — silence, inapplicability, incorporation, ambiguity, or conflict handling.
7. `## Output format` — the exact cell-level response contract.

Omit a section when it adds no operative instruction. Do not include empty headings or force a simple prompt into the full structure. Within a section, place the most outcome-determinative rule first.

### Markdown conventions

- Use `##` for major prompt sections and `###` only for genuine subcategories, such as document-type routes or individual classification definitions.
- Use bullets for independent rules. Use numbered lists only when order, priority, or fallback sequence matters.
- Put one operative rule in each bullet when practical.
- Put exact option labels, fallback values, date patterns, and output templates in backticks.
- Prefer plain imperative language. Reserve `only`, `must`, `never`, and `exactly` for actual boundaries or deterministic output requirements; do not rely on capitalization for emphasis.
- Avoid Markdown tables, HTML, block quotes, and deeply nested lists inside Harvey prompts unless the relationship cannot be expressed clearly with short bullets.
- Do not add introductory prose, restate the business objective, or explain why the column matters unless that context changes the extraction.

### Fallback vocabulary

Use the controlled fallback states defined in SKILL.md and nothing else: `Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`, `Unable to determine`. `Not stated` is reserved for Date, Number, Currency, and Duration columns, where it plays the role `Not addressed` plays elsewhere. In a Free Response column, `Unable to determine` and `Incorporated terms` may carry a short qualifier after an em dash. In a Classify column, return the exact configured option only.

### Options and examples

- For a Classify column, treat the configured Harvey options as the output vocabulary. Use the prompt to define how to choose among those exact labels; do not introduce synonyms or a competing list.
- Repeat the configured options in the prompt only when definitions, precedence, or boundary rules are needed. Record the complete option set in the maintained prompt inventory even when the UI supplies it to Harvey.
- Include an example only when it resolves a real ambiguity that a rule cannot express as clearly. Label positive and negative examples distinctly, and keep them generic unless a named fact is a legitimate matter parameter.
- An example illustrates a rule; it must not silently create an additional rule or override the stated output contract.

### Prompt format versus cell output

Markdown organizes the instructions. It does not authorize Markdown in the returned cell. Define the cell output separately and require plain text, an exact configured option, or another explicit format unless the downstream workflow genuinely needs Markdown.

Keep reasoning, evidence, quotations, citations, section numbers, and explanatory labels out of the normalized answer unless the column is specifically designed to return them. Put the output contract last so the final instruction states exactly what Harvey should return.

### Default skeleton

```markdown
## Established results

- [Upstream field]: @[Upstream field]

## Task

[State exactly what Harvey must classify, extract, or summarize.]

## Scope

- Analyze [defined subject] within the current review unit.
- Include [qualifying evidence or concepts].
- Exclude [likely false subjects, documents, or nearby concepts].

## Rules

1. [Apply any genuine order of precedence.]
2. [State the evidence required for the result.]
3. [Distinguish commonly conflated concepts.]
4. [Prohibit material unsupported inferences.]

## Fallback rules

- If the review unit is silent, return `Not addressed`.
- If the issue has no meaningful application, return `Not applicable`.
- If relevant evidence is conflicting, incomplete, or unreadable, return `Unable to determine`.

## Output format

Return `[exact required structure]`.
Do not include [prohibited output elements].
```

Remove unused sections and placeholder rules before delivery. Keep each prompt below the platform's current character limit (see platform-adaptation.md) and remove repetition before removing rules that prevent demonstrated errors.

## Harvey Table Instructions

Table Instructions apply to every column and are omitted from exports, so write them as a separate artifact, store the text in the prompt inventory, and limit them to rules that are true for every column.

Put here:

- Matter identification and the review objective in one or two sentences
- The review-subject entities with exact names, jurisdictions, and roles, plus named non-subjects (buyer, lenders, advisors) that must not be treated as subjects
- Naming and formatting conventions: exact-name rule, date pattern, currency pattern
- The fallback vocabulary and the instruction to return only the normalized answer
- The default evidence boundary: current review unit only, unless a column says otherwise

Do not put here:

- Decision thresholds, classification definitions, or exclusions that belong to one column
- Output templates or word limits
- Anything that should differ between columns

```markdown
## Matter

[Project name]. [One sentence on the review objective and whose side the review is on.] Analyze each document as a standalone record unless a column expressly says otherwise.

## Review subjects

Use these names exactly as written when an entity is the subject of an answer:

- [Exact legal name] ([jurisdiction and entity type]; [role in the group])

[Named counterparties] are not review subjects unless a column expressly asks about them.

## Shared rules

- Analyze only the document in the current row. Do not use other rows, filenames, or outside knowledge of the entities.
- Use entity and individual names exactly as printed in the document.
- Write dates as `YYYY-MM-DD`; preserve partial dates as written.
- Use only these fallback states, with the meaning each column defines: `Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`, `Unable to determine`.
- Return the normalized answer only; reasoning, quotations, section numbers, and citations belong in the evidence fields.
```

## Harvey dependent-column preamble

Use this only when the column genuinely depends on earlier results. Replace the names with the exact existing column names so Harvey can resolve the `@` references.

```markdown
Use these established results:

- Document Type: @Document Type
- Principal Entity: @Principal Entity
- Execution Status: @Execution Status

Use these results to maintain scope and consistency, but confirm the answer to this column against the current review unit. If an upstream result is `Unable to determine`, do not infer the missing fact. Apply the fallback rules below.
```

Do not restate every upstream column merely because it is available. Reference only inputs that alter the subject, applicability, evidence interpretation, or output.

## Harvey conditional detail column

Pair a controlled classification with a detail column when Harvey cannot represent both structures in one cell.

```markdown
## Established result

- [Status column]: @[Status column]

## Task

If @[Status column] is `[applicable state]`, extract [specified details] from the current review unit.

If @[Status column] is `Unable to determine`, return `Unable to determine — upstream status is unresolved`.

For all other non-applicable states, return exactly `Not applicable`.

## Rules

- Use the established result for routing, but confirm the reported details against the current review unit.
- Do not convert `Not addressed`, `Not applicable`, or `Unable to determine` into a positive finding.
- [Concept-specific inclusion and exclusion rules.]

## Output format

[Exact concise template or fallback.]
```

Use a blank instead of `Not applicable` only when the table's downstream use expressly permits blank cells. Whether a conditional column skips execution or only routes output is a platform question; see platform-adaptation.md.

## Classification column

```markdown
## Task

Classify [the defined subject] based only on evidence visible in the current document. Choose exactly one configured option.

## Options

- `[Option A]`
- `[Option B]`
- `Not addressed`
- `Not applicable`
- `Unable to determine`

## Scope

- Identify [the principal subject] from the current review unit, or use the explicitly referenced upstream subject when provided.
- Include [qualifying subjects].
- Exclude [common scope errors].

## Classification rules

### [Option A]

Use when [necessary and sufficient evidence].

Do not use when [nearby but incorrect condition].

## Fallback rules

- Use `Not addressed` when [silence condition].
- Use `Not applicable` when [document-type condition].
- Use `Unable to determine` only when relevant evidence exists but [ambiguity condition].

## Output format

Return only the exact configured option and no explanation.
```

## Structured free-response column

```markdown
## Task

Identify and concisely summarize [defined legal or factual subject].

## Response labels

Begin with exactly one of:

- `[Positive state]`
- `[Alternative state]`
- `Not addressed`
- `Not applicable`
- `Incorporated terms`
- `Unable to determine`

## Scope

- Analyze only [current review unit].
- Identify [principal subject] from the current review unit, or use the explicitly referenced upstream subject when provided.
- Do not report [common false subjects or provisions].

## Include where expressly stated

- [Material element 1]
- [Material element 2]
- [Material element 3]

## Rules

- Require [evidence threshold].
- Distinguish [frequently conflated concept A] from [concept B].
- Do not infer [common unsupported conclusion].
- Consolidate substantially similar provisions.
- Report no more than [number] material items.

## Fallback rules

- If silent, return exactly `Not addressed`.
- If irrelevant to this document type, return exactly `Not applicable`.
- If terms are incorporated but not reproduced, return `Incorporated terms — details not stated in current document`.
- If relevant evidence exists but cannot be reliably interpreted, return `Unable to determine — [brief reason]`.

## Output format

`[Response label] — [exact subject name]: [structured concise answer]`

Return no more than [word limit] words. Do not include section numbers, analysis, quotations, evidence references, or citation markers.
```

## Date column with document-type routing

Define a hierarchy for each relevant document class instead of asking for any date. A useful structure is:

```markdown
## Task

Identify [the date concept] and state what the selected date represents.

## Date-selection hierarchy

### [Document class 1]

1. Use [preferred date].
2. If absent, use [secondary date].
3. Do not substitute [common incorrect date].

### [Document class 2]

1. Use [preferred date].
2. If absent, use [secondary date].

## Excluded dates

- Filename or metadata dates
- Dates belonging only to referenced documents
- Transaction dates that do not apply to the record as a whole
- Notarization, download, retrieval, or scan dates

## Output format

`YYYY-MM-DD — [date basis]`

Preserve partial precision. Return `Not stated` when no date can be selected under the hierarchy.
```

## Evidence-status rules

Use these when a substantive answer may overstate what an unsigned or unfiled document proves:

```markdown
- Evaluate visible execution, adoption, filing, certification, or issuance evidence.
- A completed draft does not establish execution.
- A typed name or blank signature block is not a signature.
- A stated effective date does not establish that required signatures were completed.
- If the document is unsigned, describe what it `purports to` do or `would` establish.
- Do not determine ultimate validity or enforceability.
```

## Scope rules for entity-centered review

```markdown
- For a formation or governance document, analyze the entity formed or governed.
- For an amendment, analyze the entity whose organizational document is amended.
- For minutes or consent, analyze the entity whose governing body acts.
- For an ownership record, analyze the issuer unless the column expressly asks for holders.
- For an official certificate, analyze each entity whose status is certified.
- Exclude owners, parents, affiliates, counterparties, proposed entities, and DBAs merely mentioned.
```

## Final prompt check

Before delivery, verify:

- Every referenced column exists, precedes the dependent logic, and uses the platform's exact reference syntax.
- The prompt references only upstream results that materially affect its analysis.
- The downstream column confirms its substantive answer against the current review unit rather than treating the upstream result as sufficient evidence.
- Upstream fallback states have explicit routing behavior.
- Fallback states come from the controlled vocabulary; no synonyms.
- Rules that apply to every column live in Table Instructions rather than being repeated in each prompt.
- Included and excluded concepts do not overlap.
- Silence is not labeled uncertainty.
- Unsigned evidence is not described as a completed act.
- Labels and output examples agree.
- The response is concise enough for a table.
- Citation artifacts and clause inventories are prohibited when not requested.
- The prompt is below the platform's character limit.
