# Prompt Inventory — [Table name]

One record per column. Keep this file outside the platform; Harvey exports omit Table Instructions and do not version prompts, so this is the authoritative history. Update the record and its change log every time a prompt changes, even for a one-word fix.

Copy `## Column records` → `### [Column name]` once per column. Delete these instructions before sharing.

## Table

- Matter:
- Platform:
- Review unit (what one row represents):
- Grouping used (yes/no; maximum documents per unit):
- Intended reviewers and downstream use:
- Inventory version:
- Last full run:
- Last evaluated (see evaluation log):

## Table Instructions

- Version:
- Last changed:

```markdown
[Paste the current Table Instructions exactly as entered in the platform.]
```

## Column index

Order columns as they appear in the table. Write dependencies in the platform's syntax.

| # | Column | Native type | Upstream dependencies | Downstream dependents | Version | Last evaluated | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | — | | v1.0 | | draft |

Status values: `draft`, `testing`, `verified`, `retired`.

## Column records

### [Column name]

- Native type:
- Configured options (Classify only), in UI order:
- Upstream dependencies:
- Downstream dependents (rerun these when this column changes):
- Purpose (one attorney-readable sentence):
- Version:
- Last evaluated:
- Enhancement focus:

#### Original prompt

```markdown
[Starter prompt as first written, preserved for comparison.]
```

#### Current prompt

```markdown
[Exact text currently in the platform.]
```

#### Change log

| Version | Date | Change | Failure class addressed | Rerun scope | Regressions |
| --- | --- | --- | --- | --- | --- |
| v1.0 | | Initial draft | — | — | — |

## Human-review fields

Keep these as separate table columns or a separate sheet, not inside AI-extraction prompts:

- Reviewer
- Validation status
- Operative version confirmed
- Issue status
- Deal consequence
