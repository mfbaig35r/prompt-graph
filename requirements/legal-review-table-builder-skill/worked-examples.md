# Worked Examples

Fully realized prompts for one Harvey Review Table, showing what the construction standard in [prompt-patterns.md](prompt-patterns.md) looks like once the placeholders are filled. Use these to calibrate tone, density, and length. Do not copy them into an unrelated table; the rules reflect this matter's document set. The matter and every name are fictional.

## The table

Project Harbor: buyer-side entity diligence on Harbor Logistics Holdings, LLC and its two subsidiaries. One row is one document. Grouping is not used. Documents include certificates of formation, articles of incorporation, operating agreements, bylaws, written consents, minutes, and good-standing certificates.

Two columns are shown. `Execution Status` is an orientation column that later columns use for routing. `Signatories` is the first column that depends on it.

Dependency map for the columns shown:

- `Execution Status` (Classify; no upstream) → `Signatories` (Free Response)
- `Execution Status` also feeds `Board and Member Actions`, `Amendment Detail`, and `Human Review Flags` (not shown)

## Table Instructions

About 1,300 characters. Stored in the prompt inventory because exports omit it. Note what is absent: no decision thresholds, no column-specific exclusions, no output templates. Those belong to the columns that own them.

```markdown
## Matter

Project Harbor. Buyer-side entity diligence on the target group listed below. Analyze each document as a standalone record unless a column expressly says otherwise.

## Review subjects

Use these names exactly as written when an entity is the subject of an answer:

- Harbor Logistics Holdings, LLC (Delaware limited liability company; parent)
- Harbor Freight Services, Inc. (Texas corporation; wholly owned subsidiary)
- Harbor Cold Chain, LLC (Delaware limited liability company; wholly owned subsidiary)

Northgate Acquisition Corp. is the buyer. It is a counterparty, not a review subject, unless a column expressly asks about the buyer.

## Shared rules

- Analyze only the document in the current row. Do not use other rows, filenames, or outside knowledge of the entities.
- Use entity and individual names exactly as printed in the document; do not shorten, expand, or correct them.
- Write dates as `YYYY-MM-DD`. Preserve partial dates as written when the document gives less precision.
- Use only these fallback states, with the meaning each column defines: `Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`, `Unable to determine`.
- Return the normalized answer only. Reasoning, quotations, section numbers, and citations belong in Harvey's evidence fields, not in the cell.
```

## Column: Execution Status

- Native type: Classify
- Configured options, in UI order: `Filed or issued`, `Fully executed`, `Partially executed`, `Unsigned`, `Not applicable`, `Unable to determine`
- Upstream: none
- Downstream: `Signatories`, `Board and Member Actions`, `Amendment Detail`, `Human Review Flags`
- Purpose: state what the document visibly proves about its own completion, so later columns can describe an unsigned consent as a proposal rather than an approved action.

`Document Type` exists in this table but is not referenced here. Execution status is read from the same visible evidence whatever the document type, so the reference would add an input without changing the analysis. That is the test for whether to reference an upstream column at all.

About 2,500 characters.

```markdown
## Task

Classify the visible completion status of the document in the current row. Choose exactly one configured option.

## Scope

- Evaluate only signature blocks, electronic-signature markers, conformed signatures, filing stamps, file numbers, and certification language visible in this document.
- Include signature pages, counterpart pages, and stamped cover pages that belong to this document.
- Exclude signature and filing evidence on exhibits, attachments, or referenced documents; that evidence describes those documents, not this one.

## Classification rules

Apply the first rule that fits.

1. `Filed or issued`: the document bears a government filing stamp, a file number with filing date, or certification language from a Secretary of State or equivalent office, or is a certificate issued by such an office. Use this even when the document also carries organizer, incorporator, or officer signatures; those signers are reported in the Signatories column.
2. `Fully executed`: every signature block the document provides for a party bears a signature marker.
3. `Partially executed`: at least one party signature block bears a signature marker and at least one does not.
4. `Unsigned`: the document provides party signature blocks and none bears a signature marker. This includes drafts with typed names, blank signature lines, and a "signature page follows" reference with no signed page attached.
5. `Not applicable`: the document provides no signature block and no filing or certification evidence, such as a cap table spreadsheet, organizational chart, memorandum, or correspondence.

A signature marker is a handwritten signature, an electronic-signature block from a signing platform, or a conformed signature shown as `/s/` followed by a name. A typed name without one of these, a blank signature line, or a stated effective date is not a signature marker.

Count signature blocks for parties only. Do not count notary, witness, or attestation blocks toward execution status.

## Fallback rules

- Use `Unable to determine` only when signature or filing evidence exists but cannot be read, when a signature page is referenced but missing, or when the document visibly conflicts with itself about execution.
- Do not treat a stated effective date, a "duly executed" recital, or a cover email describing the document as signed as evidence that signatures were completed.

## Output format

Return only the exact configured option. Do not add explanation, dates, names, or citation markers.
```

## Column: Signatories

- Native type: Free Response
- Upstream: `@Execution Status`
- Downstream: `Human Review Flags`
- Purpose: identify who signed, for which party, and in what stated capacity, so the reviewer can check authority without opening the document and can see missing counterparties on partially executed documents.

About 2,500 characters.

```markdown
## Established results

- Execution Status: @Execution Status

Use this result for routing only. Confirm every reported name, title, and signature against the signature blocks in the current row.

## Task

If Execution Status is `Fully executed` or `Partially executed`, list each party the document provides a signature block for, the individual who signed for that party, the individual's stated title or capacity, and whether that block is signed.

If Execution Status is `Filed or issued`, list any visible individual signer of the filed instrument, such as an organizer, incorporator, or authorized person, in the same form. If no individual signer is visible, return `Not applicable — government filing or certificate without individual signer`.

If Execution Status is `Unsigned` or `Not applicable`, return exactly `Not applicable`.

If Execution Status is `Unable to determine`, return exactly `Unable to determine — upstream execution status is unresolved`.

## Rules

- Use party and individual names exactly as printed in the signature block, including entity suffixes.
- Report the title or capacity exactly as printed under the signature line, for example `Manager`, `Authorized Signatory`, or `Sole Member`. Write `capacity not stated` when none is printed.
- When an individual signs for one entity in its capacity as manager or member of another (a layered block), report the outermost party as the party and describe the chain in the capacity field.
- Report each party once, even if it signs multiple counterparts.
- Do not report notaries, witnesses, or attesting secretaries as signatories.
- Do not infer a signer's authority, and do not state whether the signature was authorized or effective.
- If a signature marker is present but the signer's name is illegible and not typed beneath it, report the party with `signer name illegible`.

## Fallback rules

- If the upstream result is `Partially executed` but every block in the current row appears signed, or `Fully executed` but a block is blank, report what the current row shows and begin the answer with `Conflicts with Execution Status —`.

## Output format

One line per party, in the order the signature blocks appear:

`[Party name] — [Signer name], [Title or capacity] ([Signed | Unsigned])`

List no more than 8 parties. If there are more, list the first 8 and end with `and [N] additional parties`. Return no more than 120 words. Do not include dates, section numbers, quotations, or citation markers.
```

## Why the prompts look this way

- Execution Status has no `Established results` section because it references nothing. Adding one for a column that has no real dependency is the most common way skeletons get misused.
- The classification rules are a numbered list because precedence matters: a filed instrument with an organizer signature must land on `Filed or issued`, not `Fully executed`. The signature-marker definition is prose because it serves several rules at once.
- Signatories routes on every upstream state explicitly, including the two that collapse to `Not applicable`. No state reaches the substantive extraction silently.
- The `Conflicts with Execution Status —` prefix is a validation signal for the reviewer, not a new fallback state. `Human Review Flags` downstream picks it up. Keep such prefixes rare and name them in the inventory so they are not mistaken for vocabulary drift.
- Both prompts end with the output contract, and neither returns Markdown.
- Each prompt is about 2,500 characters, a quarter of the 10,000-character per-query limit, leaving room for the rules that testing will add. Whether Table Instructions count toward a column's query length is not confirmed; budget as if they do.
- Deliberately absent: explanation of why execution matters to the deal, matter-specific names (they live in Table Instructions), and examples. The rules already resolve the ambiguities testing on this corpus exposed: conformed signatures, notary blocks, and layered signature blocks.

## Inventory entry for these columns

The records in `assets/prompt-inventory-template.md` for these two columns would read, in the column index:

| # | Column | Native type | Upstream dependencies | Downstream dependents | Version | Last evaluated | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | Execution Status | Classify | — | Signatories; Board and Member Actions; Amendment Detail; Human Review Flags | v1.2 | 2026-09-02 | verified |
| 4 | Signatories | Free Response | @Execution Status | Human Review Flags | v1.1 | 2026-09-02 | verified |

and the change log for Execution Status would show why v1.2 exists:

| Version | Date | Change | Failure class addressed | Rerun scope | Regressions |
| --- | --- | --- | --- | --- | --- |
| v1.0 | 2026-08-20 | Initial draft | — | — | — |
| v1.1 | 2026-08-26 | Added `/s/` conformed signature to signature-marker definition | Evidence overstatement (conformed closing set returned `Unsigned`) | Execution Status + 4 dependents | None |
| v1.2 | 2026-09-02 | Excluded notary and attestation blocks from party count | Scope leakage (blank notary block counted as a party block; returned `Partially executed`) | Execution Status + 4 dependents | None |
