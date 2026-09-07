# Decisions

Every place the requirements left a choice open, and every place the build deviates from
them, with the reason. Section numbers refer to `requirements/prompt-graph-mcp-requirements.md`.

## Tool surface

**21 working names became 18 tools (§7).** Six of the listed tools were fragments of one
user task and were folded into the verb the user actually says. Nothing in §7 is
unreachable.

- `matter_overview` → folded into `matter_open`. Creating and opening a matter return the
  same overview; "where are we?" is the same call as "open it".
- `graph_check` + `consistency_check` → `suite_check`, with a `checks=` filter (families:
  prompts, graph, parameters, consistency). The user asks one question ("is anything wrong
  with the suite?"); splitting it forces Claude to orchestrate.
- `parameter_resolve` → `parameter_set`, which declares, resolves, and binds consumers in
  one call. `parameter_bindings` is the `consumers` list it returns and what
  `impact_of_change` and `columns_find(consumes_parameter=)` report.
- `propagation_preview` → `impact_of_change(parameter=..., new_value=...)`. For a
  parameter, the result lists consumers, every Table Instructions and prompt that contains
  the current value (bound or not), and the downstream columns in rerun order. Same
  question, one answer.

**One tool was added: `column_revise`.** The requirements version prompts but give no way
to store one revised prompt other than re-ingesting the whole table. After the skill drafts
v1.1 of one column, a paralegal needs "store this as the new version" to be one call. The
same tool carries rename (which §5 says must be explicit), status changes, and metadata.

**Names, not ids.** Every tool takes matter, table, column, and parameter by name,
case-insensitively and whitespace-normalized. Ids are returned for Claude's convenience
and never required.

**Errors are returned, not raised.** A `PromptGraphError` (unknown matter, malformed
record) comes back as `{"error": "..."}` in the tool result rather than an MCP tool error.
The message is written for the model and lists what does exist ("Tables: …"). Genuine bugs
still raise.

## Vocabulary and taxonomy (deviation from §6)

**Failure classes are the skill's sixteen, not the requirements' eight.** §6 lists eight
slugs including `output_format_error`, which does not appear in the skill. The build prompt
says the taxonomy comes from the skill and must match exactly, so `FAILURE_CLASSES` is the
sixteen-row table in `references/evaluation.md`, in the skill's order, with label-form
aliases accepted (`"Evidence overstatement"` → `evidence_overstatement`). The requirements'
`output_format_error` is not accepted; the skill's equivalents are `output_leakage`,
`vocabulary_drift`, and `verbosity`. An unknown class is stored as submitted and reported
as `FAILURE_CLASS_INVALID` so the log is never silently dropped.

**Fallback synonyms are exactly the six the requirements list** (`N/A`, `None`, `Unclear`,
`Silent`, `Unknown`, `TBD`). The skill names four of them; the other two are reasonable and
listed in §8, so they stay.

**Coverage dimensions are the fourteen in the evaluation log template**, keyed by short
slugs. The grouped-evidence dimension is only applicable when the table has grouping
enabled; ticking it on a non-grouped table is reported.

## Data model

**Matching on ingest is by (table, column name).** Unchanged text creates no version;
changed text creates a new minor version with a change note naming the source; a new name
is a new column; a stored column absent from the submission is reported as
`COLUMN_ABSENT_FROM_INGEST` and left alone. Nothing is retired by inference.

**Version scheme is `v{major}.{minor}`**, matching the skill's inventory template. Ingest
assigns v1.0; `column_revise` increments the minor number unless `bump="major"`.

**Standards are versioned rows**, one current per scope. Fields omitted from
`standard_set` carry forward. A matter overlay may set entities, objective, naming rules,
and conventions freely. For the four constrained fields (fallback vocabulary, date
pattern, currency pattern, evidence boundary) a value that differs from a non-empty firm
value is stored as submitted, reported as `STANDARD_CONTRADICTS_FIRM`, and ignored when the
effective standard is computed. Storing it keeps the attempt visible; ignoring it keeps
consistency checks anchored to the firm baseline.

**The firm baseline is seeded** from the skill on first migration: the five fallback
states, `YYYY-MM-DD`, exact-name rule, current-review-unit boundary, no currency pattern.
Changing the firm vocabulary is allowed but reported (`STANDARD_VOCABULARY_NOT_SKILL`).

**Dependencies are materialized edges** of three kinds. `intra_table_ref` edges are rebuilt
from the prompt text (and declared `upstream_refs`) every time a column's text changes.
`cross_table_parameter` edges are rebuilt from bindings every time `parameter_set` runs and
after every ingest: source column → each bound column, and for a table-level binding →
every active column of that table. A parameter without a source column produces no edges
(impact still works through bindings). `advisory` edges are declared on the column record
and only ever touched explicitly.

**`@Column` parsing** resolves each `@` against the table's known column names, longest
match first, case-insensitive, requiring a word boundary after the name. Only when nothing
matches does it fall back to a heuristic token (words up to a delimiter or common stop
word) so the unresolved name reported is close to what was typed.

**Two optional column fields were added** beyond §5: `role` (the skill's staged pattern:
orientation, extraction, validation, reconciliation, human_review) so ordering violations
can be checked deterministically, and `concept` (a short tag) so the same concept can be
compared across tables without name matching. Both are optional; the checks that use them
fall back to heuristics when absent.

**Runs snapshot the Table Instructions version too**, not only prompt versions, because a
changed instructions text changes every column's effective prompt.

**Provenance** is a single append-only table keyed by entity type and id; `column_read`
with history exposes it as the change log.

## Graph semantics (§6, §7)

**Direct vs transitive.** In `impact_of_change`, a column is `direct` when an edge runs
from the subject to it and `transitive` otherwise. A table-level parameter binding fans out
to every column in the consuming table, so all of them are direct consumers of the
parameter's source column; their intra-table dependents are also direct if they are in the
fan-out. This is by definition rather than by convenience.

**Rerun order** is Kahn's algorithm over the affected subgraph, always taking the ready
node with the smallest (table position, column position), so the order groups by table
where dependencies allow. Nodes that cannot be ordered because of a cycle are appended in
table order, `in_cycle` is set only on nodes that actually lie on a cycle, and a
`GRAPH_CYCLE` finding is attached. No traversal can loop.

**Staleness.** `never_run`: no snapshot includes the column. `direct`: the current prompt
version differs from the one in the column's last run, the table's current instructions
version differs, or a bound parameter was resolved after that run started. `transitive`:
an upstream column (any edge kind, any table) is stale, or its current version is newer
than this column's last run. When the upstream was in the same run's snapshot the
comparison is by version id; otherwise by timestamp (microsecond ISO 8601). Propagation
iterates to a fixed point bounded by the node count.

**Cycle-membership threshold for `CONTROL_PLANE_NARRATIVE`** is two or more intra-table
dependents of a Free Response or Verbatim column. The skill says "many"; two is where a
wording change upstream starts altering multiple results.

## Validation heuristics (§8)

The rules are lexical. Where a rule needs to know what a prompt "presents as returnable",
the lint treats backticked tokens and anything after "return" / "return exactly" as output
tokens, and ignores a line containing a prohibition ("do not", "never", "instead of", …).
That is the skill's own convention (exact labels in backticks) and it lets "Do not return
`N/A`" pass while "return `N/A`" is reported.

- **Classify labels not configured**: backticked or returned tokens starting with an
  uppercase letter, up to 60 characters, not an option, fallback state, or column name.
  Lower-case tokens, pattern tokens (`YYYY-MM-DD`, `/s/`), and `@` references are skipped.
- **Em-dash qualifier in Classify**: `Unable to determine —` / `Incorporated terms —`
  followed by text, or the words "qualifier" / "after an em dash".
- **Output contract**: an `Output`/`Response format` heading, or any "return" instruction.
- **Markdown in cell**: a line outside the output section that mentions Markdown, bullets,
  bold, italics, or headings in connection with the answer, without a prohibition, when the
  output section does not itself allow Markdown.
- **Date patterns**: sixteen recognised pattern tokens. **Currency**: symbol/code amounts
  normalised to a style string (`USD 9,999.99`, `$9,999.99`, `9,999.99 USD`). Both compare
  against the standard's pattern, or flag any divergence when no pattern is set.
- **Entity name variants**: the base name (suffix stripped) is searched in Table
  Instructions and prompts with an optional suffix; any printed form that is not the exact
  standard name is reported. Names shorter than four characters are skipped.
- **Same concept, different names**: explicit `concept` tags first; then identical names in
  different tables with different type, options, or fallback set; then a token-overlap
  heuristic (Jaccard ≥ 0.6 on two-plus-word names) reported with `"heuristic": "token
  overlap"` so Claude can weigh it.

## Evaluation (§7 P2)

**An open failure** is a (column, test document) pair whose most recent result, ordered by
run start then insertion, failed. It closes when a later result for the same pair passes.
No free-text field is parsed for this.

**`eval_record` stores everything and reports problems** (invalid class, invalid error
type, version mismatch with the run snapshot, failure fields on a pass, missing class on a
fail) rather than rejecting rows, so a paralegal's batch is never half-applied.

**`run_compare`** defaults to the two latest runs of the table and reports fixed, still
failing, newly failing (also a `REGRESSION` finding), still passing, and documents present
in only one run.

**`FAILURE_CLASS_RECURRING`** fires when a class is open on three or more columns or in
more than one table. Systematic problems are what single-column review misses.

## Coverage (§9)

**`kind` is required on every assertion** (`extraction` or `judgment`) and the server never
infers it. The requirements say Claude proposes the mapping and the server audits it.
Inferring judgment from keywords would put a legal characterisation in code and would fail
silently on phrasing the keyword list missed. A judgment assertion is reported as a
boundary whether or not it has evidence inputs; it is never a gap.

**Reliability**: a source column is reliable when it has a recorded run, no open failure,
is not stale, and its table's latest run ticks every applicable dimension. An assertion is
reliably covered if any active source is reliable, otherwise nominally covered with the
per-column reasons. Before any evaluation, everything is nominal; that is the honest state.

**Unsourced columns** are every active column that feeds no assertion. Retired columns are
excluded.

## §12 open questions: defaults chosen

1. **Deployment and concurrency.** stdio-local, single database file, WAL mode. The
   `PROMPT_GRAPH_DB` variable lets a firm put the file on a controlled volume. Concurrent
   writers from several attorneys are not coordinated beyond SQLite's busy timeout (5 s);
   a hosted deployment would need a different transport and is not built.
2. **Access control and confidentiality.** None in the server. The database is a matter
   file; the README says to treat it as one (directory permissions, backups, retention).
   The `actor` argument on writing tools records who did what in provenance but is not
   authenticated.
3. **Harvey connector.** P4 not built. No Harvey I/O exists in this codebase.
4. **Editing outside Claude.** The inventory is authoritative by policy. Reconciliation
   path: re-ingest the Harvey export; changed prompts become new versions, missing columns
   are reported, and `staleness_report` shows what moved.
5. **Firm standard authorship.** Whoever runs `standard_set(scope="firm")`. Every change
   is a new version with a change note and actor; vocabulary changes are reported.
6. **Memo outline reuse.** Per matter, versioned. The demo fixture's outline is the
   nearest thing to a template; no template mechanism is built.

## Scope kept out on purpose

- No MCP resources mirror the skill's reference files (§4).
- No prompt text is ever generated or rewritten, including on rename: prompts that still
  reference the old `@name` are reported, not edited.
- No legal reasoning in any string. Observations name what is, never what to do.

## Stack notes

- Python 3.11 floor (the requirements say 3.11+; the venv used for the build is 3.11.13).
- `mcp` SDK 1.x FastMCP with pydantic models for nested inputs, so the tool schemas carry
  field descriptions the model can read.
- `sqlite3` from the standard library; migrations are SQL scripts in `db.py` applied in a
  transaction and recorded in `schema_version`.
- `ruff` ignores E501 only; long finding strings are the reason.
