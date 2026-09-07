# Evaluation Log — [Table name]

Companion to the prompt inventory. One row per test document and column pair you checked. Record passes as well as failures, so a later reader can tell "tested and correct" from "not tested." A `.csv` version of the log table sits beside this file for spreadsheet work.

## Run

- Table / inventory version:
- Prompt versions under test:
- Corpus (size, source, date assembled):
- Evaluator:
- Date:

## Test-set coverage

Tick each dimension the corpus covers. An unticked dimension is open risk, not a pass.

- [ ] Each material document type
- [ ] Single-subject and multi-subject files
- [ ] Signed, partially signed, unsigned, filed, and government-issued documents
- [ ] Amendments, restatements, compilations, and attachments
- [ ] Documents that expressly address the issue
- [ ] Documents that are silent
- [ ] Documents that incorporate external terms
- [ ] Incomplete, illegible, or internally conflicting records
- [ ] Multiple records about the same underlying subject
- [ ] Each upstream fallback state reaching each dependent column
- [ ] Multi-hop dependency chains and a changed upstream result
- [ ] Conditional columns with the condition met and not met
- [ ] Locked and unlocked cells during selective reruns
- [ ] Grouped sets with consistent, complementary, and conflicting evidence (if grouping is used)

## Log

Failure class uses the taxonomy in `references/evaluation.md`. Error type is `substantive`, `evidentiary`, or `formatting`. Leave failure fields blank for a pass.

| ID | Test document | Column | Prompt version | Actual answer | Evidence relied on | Expected behavior | Pass/Fail | Failure class | Error type | Revision | Rerun scope | Result after rerun | Regressions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | | | | | | | | |

## Summary

- Failures by class:
- Columns revised and new versions:
- Regressions recorded:
- Source-document conflicts flagged for attorney review (not prompt defects):
- Untested dimensions carried forward:
