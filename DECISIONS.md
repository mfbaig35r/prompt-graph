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

**Closed sets are enums at the tool boundary, soft inside batches.** After an ergonomics
review (2026-09-07), every scalar argument with a closed value set (`scope`, `side`, `status`,
`role`, `bump`, `group_by`, `source_type`, `native_type` on `prompt_check` and
`column_revise`, parameter status, check families) is a `Literal` in the schema, case-folded
on the way in so `"Draft"` is `draft`. Fields inside batch models (`ColumnRecord.native_type`,
`EvalRecord.failure_class`, `error_type`) stay strings, because a `Literal` there would let one
bad record reject a whole batch at the client; the server stores the batch and reports the bad
record instead. Every top-level parameter carries a description in the schema.

**Matter discovery and creation.** `matter_open` with no name lists the matters. `create`
defaults to false: a typo returns the real matters instead of silently creating a phantom
matter in a client-data store, at the cost of one extra call on first creation.

**`columns_find` pages.** `limit` (default 100, max 500) and `offset`, with `total` and
`truncated` in the result, so a twenty-table matter cannot return 130KB in one call.

**Coverage findings are specific.** `COV_NOMINAL_ONLY` names each unreliable source and its
reasons in the observation, so the most specific sentence is the one the model leads with;
`sections[]` remains the structured truth. The per-source `COV_SOURCE_STALE` finding was
removed as a duplicate.

## Vocabulary and taxonomy (deviation from §6)

**Failure classes are the skill's nineteen, not the requirements' eight.** §6 lists eight
slugs including `output_format_error`, which does not appear in the skill. The build prompt
says the taxonomy comes from the skill and must match exactly, so `FAILURE_CLASSES` is the
nineteen-row table in `references/evaluation.md` (the 2026-09-04 bundle, which adds
Suppressed value, Type rejection, and Dead reference over the flat copy that shipped
beside it), in the skill's order, with label-form
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
- **Character-count rule**: any `N characters` on a line that is not a prohibition. The
  bundle says such rules are applied unreliably; word limits are allowed.
- **Dead reference**: an `@Column` that resolves, but whose name does not appear outside
  the Established results section (declaration lines of the form `- Label: @Name` do not
  count as use). A generic phrase such as "any established result" counts as use of every
  declared input. Needs table context, so it runs on stored prompts and on drafts checked
  with a matter and table.
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

## Addendum A (built 2026-09-07)

**A.1 freshness.** Migration 2 adds `document_set_snapshot`, `vault_project_id` on matter and
table, and `run.document_set_snapshot_id`, so no run recorded from now on lacks the field. The
vault project lives on the table with a matter-level default, because tables in one matter
can run against different projects. The addendum's two tools are one: `freshness_check`,
which compares by default and observes with `refresh=true`, from the Vault API when
`HARVEY_API_KEY` is set or from a manual count otherwise. The manual path is first-class,
not a fallback: Konexo's seats have no API. `run_record` links the latest snapshot for the
table's project, or records a manual one from `documents_ready`. Findings carry the
observation's provenance. The API client is stdlib only with an injectable fetcher, filters to
`ready_to_query`, skips `deleted_at`, paginates by cursor, caches for five minutes against
the ten-a-minute limit, and fails loudly on an unexpected response shape. Freshness is
surfaced beside staleness in the overview, as a reliability reason in coverage, and in
readiness; it is never folded into staleness.

**Corrected 2026-09-15: enumeration is budgeted.** One call spends at most eight Vault
requests, shared across every project it observes, because the ten-a-minute limit is per
organisation and is shared with everything else the firm is doing in Harvey. Unbudgeted, a
vault holding more than roughly 800 ready documents could never be observed at all: the poll
took a 429 partway through, discarded the pages already fetched, and every retry restarted
from the first cursor and spent the budget again. An oversized vault now produces
`DOCSET_TOO_LARGE_TO_ENUMERATE` and **no snapshot**, because a prefix of the file list is not
the document set and recording it would read later as documents removed. Projects crowded out
by an earlier one produce `DOCSET_POLL_BUDGET_SPENT` rather than being skipped silently. The
manual path is unaffected and remains the answer for a large vault.

**A.2 reverse coverage.** `impact_of_change`, `staleness_report`, and `freshness_check` end
with `memo_consequences`: assertions whose sources are affected, `unsupported` when every
active source is, `weakened` when some are. The changed column itself counts as affected,
so a leaf column that sources an assertion still surfaces it. Judgment assertions are
included, labelled by kind, because their evidence inputs moved.

**A.3 export.** `matter_export` writes one JSON document, `export_format_version` 1, to an
`exports` folder beside the database by default (or a given path, or inline). It includes
the coverage report computed at export time and the provenance log. No import is built.

**A.4 readiness.** `table_readiness` composes `suite_check` scoped to the table, lifecycle
state, unresolved consumed parameters, open failures, unticked dimensions, and freshness,
grouped by cause with counts. No verdict field exists by design.

**Not built from the addendum.** A.5 is a skill change (draw the graph), recorded in the
skill's Orchestrate reference. The Review Tables API cannot read column definitions
(verified 2026-09), so manual ingest stays primary; it can read row results, so a result
importer is the next P4 candidate.

**Corrected 2026-09-16: a metadata-only revise is now logged.** `column_revise` writes a
prompt version only when the text changes, and `change_note` used to be consumed only by that
version. So a retire, a role change or a status change dropped its explanation, and wrote no
provenance at all: the action was invisible and the reason gone. Metadata changes now write
their own provenance row, action `retire` or `revise`, carrying the changed fields, the note,
the failure class and the actor. A revise that also writes a version still logs once, not
twice. Found in a real matter where nine columns were retired and all nine reasons were lost.

**Coverage is a `suite_check` family (2026-09-16), carrying half its report.** Prompt lint
tests a rule and evaluation tests a rule's answers; neither can detect the failure where every
rule is correct and the suite still cannot support the deliverable, because that is a property
of the set. Coverage was a separate tool, and `table_readiness` composes `suite_check`, so a
table could read ready while supporting nothing the memo needs.

Only the actionable half is carried. `COV_NOMINAL_ONLY` is every sourced assertion until a run
exists, which is the expected state of any matter that has not run and is already reported by
staleness; `COV_JUDGMENT_BOUNDARY` is a deliberate boundary. On a real matter those are 123 rows
of noise against 53 of signal, so including them would bury `COV_EXTRACTION_GAP`, which is the
one that means a hole. A matter with no outline at all reports `MEMO_OUTLINE_MISSING`.

Matter-level findings are not attributed to a table: an extraction gap and a missing outline are
holes in the suite, not in whichever table the check was scoped to, so both are suppressed when
`table` is given. A rule feeding no assertion is attributable, and only that table's are shown.

## Contract-review extension (proposed 2026-09-15)

Full delta in `requirements/prompt-graph-contract-review.md`. Nothing is built. Migration 3
is written and verified against a copy of a real database, but it is not in `MIGRATIONS`.

**One schema carries both ontologies, rather than a shared governance core plus two domain
packages.** Everything the extension adds except `rule_position` is governance metadata any
ontology would want: ownership, review cadence, severity, applicability, per-result facets.
`rule_position` is the exception. Storing preferred, acceptable, and unacceptable positions
asserts that a rule is a negotiation object, which an M&A extraction column is not and never
will be, so it is the point where the schema stops being neutral about legal content.

Kept as one schema anyway. A nullable child table costs a diligence matter nothing: no rows,
no joins on any existing query path, and the migration is additive. Splitting now means
guessing where the seam runs from one real user; splitting later means drawing it from two.
The cost of being wrong is asymmetric in the same direction, because an unused table is cheap
while a premature package boundary is expensive to move once tools and tests are written
across it.

Revisit when a second ontology needs a field that *contradicts* the first rather than merely
extending it. A shared column whose vocabulary has to mean different things per domain is the
signal, not table count.

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
