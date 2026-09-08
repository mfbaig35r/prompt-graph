# prompt-graph — build plan

Written before implementation, from `requirements/prompt-graph-mcp-requirements.md` and the
`legal-review-table-builder` skill (v1). Choices the requirements leave open are recorded in
`DECISIONS.md`; this file is the shape of what gets built.

## 1. Tool surface: 21 working names consolidated to 18, then 21 with Addendum A

The requirements list 21 working names. Six of them are fragments of the same user task, so
they are folded into the verb the user actually says. Nothing is dropped; every capability in
§7 is reachable from one call.

| # | Tool | Phase | Absorbs | User says |
| --- | --- | --- | --- | --- |
| 1 | `matter_open` | P0 | `matter_overview` | "Open Project Harbor" / "Where are we on Harbor?" — creating and opening return the same overview, so one tool. |
| 2 | `standard_set` | P0 | — | "Set the firm baseline" / "For this matter the entities are…" |
| 3 | `table_ingest` | P0 | — | "Here is the entity table" — accepts columns **and** Table Instructions in one call, because a Harvey table has both. |
| 4 | `table_instructions_set` | P0 | — | "Update the Table Instructions on the contracts table." |
| 5 | `column_revise` | P0 | *(new)* | "Store this as v1.1 of Execution Status" / "rename" / "retire" / "mark verified". Without this a one-column revision means re-ingesting thirty columns. Rename is explicit here, never inferred by ingest. |
| 6 | `column_read` | P0 | — | "Show me the Signatories prompt and its history." |
| 7 | `columns_find` | P0 | — | "Which Classify columns are still in draft?" / "What consumes Target Legal Name?" |
| 8 | `prompt_check` | P0 | — | "Check this draft before I store it." |
| 9 | `impact_of_change` | P1 | `propagation_preview`, `parameter_bindings` | "If the entity table's name column changes, what do I rerun?" / "If Target Legal Name becomes X, what needs editing?" — for a parameter it returns consumers, every Table Instructions and prompt containing the old value, and the downstream columns. Same question, one answer. |
| 10 | `suite_check` | P1 | `graph_check`, `consistency_check` | "Is anything wrong with the suite?" — cycles, unresolved refs, ordering, orphaned parameters, dangling bindings, vocabulary/date/currency drift, entity-name variants, duplicate concepts, plus the stored-prompt lint. `checks=` narrows it when a user asks for one family. |
| 11 | `staleness_report` | P1 | — | "What's stale since the last run?" |
| 12 | `parameter_set` | P1 | `parameter_resolve` (+ binding management) | "Target Legal Name is Harbor Logistics Holdings, LLC, from the entity table, used by these six tables." Declare, resolve, and bind in one call. |
| 13 | `run_record` | P2 | — | "We ran the charter table today against the 14-document test set." |
| 14 | `eval_record` | P2 | — | "Log these results" (batch; mirrors `evaluation-log-template.csv`). |
| 15 | `failures_summary` | P2 | — | "What's failing, by class?" |
| 16 | `run_compare` | P2 | — | "Did v1.2 fix the notary problem without breaking anything?" |
| 17 | `memo_outline_set` | P3 | — | "Here is the memo outline and what each section has to say." |
| 18 | `coverage_check` | P3 | — | "Can the suite support the memo?" |
| 19 | `freshness_check` | A.1 | `document_set_refresh`, `freshness_report` | "Has the data room grown since we ran the leases table?" One tool: compares by default, observes with `refresh=true` (Harvey Vault API or a manual count). |
| 20 | `table_readiness` | A.4 | — | "Is the charter table ready to run against the real vault?" Composes every check for one table, grouped by cause, no verdict. |
| 21 | `matter_export` | A.3 | — | "Give me a record of everything we reviewed and when." One versioned JSON document. |

Names: tools take `matter`, `table`, `column`, `parameter` by **name** (case-insensitive,
whitespace-normalized). Internal ids are returned but never required.

Every tool returns `{ ..., "findings": [Finding] }`. A Finding is exactly
`{code, subject_type, subject_id, subject_name, observation, evidence}` — one factual sentence,
no advice, no severity words.

## 2. Schema (SQLite, WAL, `schema_version` table)

```
schema_version      version, applied_at
standard            id, scope('firm'|'matter'), matter_id, version, fallback_vocabulary(json),
                    naming_rules, date_pattern, currency_pattern, default_evidence_boundary,
                    entities(json: [{name, jurisdiction, role, is_subject}]), objective,
                    conventions(json), created_at, change_note, is_current
matter              id, name UNIQUE, objective, side('buy'|'sell'|null), status, created_at
review_table        id, matter_id, name, review_unit, platform, grouping_enabled,
                    max_docs_per_unit, stage, position, created_at   UNIQUE(matter_id,name)
table_instructions  id, table_id, version, text, change_note, created_at, is_current
column              id, table_id, name, position, native_type, configured_options(json),
                    purpose, role, concept, status, created_at, retired_at   UNIQUE(table_id,name)
prompt_version      id, column_id, version('v1.0'), major, minor, text, char_count,
                    change_note, failure_class_addressed, created_at, is_current
dependency          id, from_column_id(upstream), to_column_id(downstream),
                    kind('intra_table_ref'|'cross_table_parameter'|'advisory'),
                    declared_by('ingest'|'user'|'parameter'), parameter_id, note
                    UNIQUE(from,to,kind)
shared_parameter    id, matter_id, name, value, source_column_id, source_table_id,
                    resolved_at, status('unresolved'|'resolved'|'contested'), note
                    UNIQUE(matter_id,name)
parameter_binding   id, parameter_id, consuming_table_id, consuming_column_id,
                    binding_site('table_instructions'|'column_prompt')
run                 id, table_id, started_at, note, evaluator, corpus_note,
                    document_set_snapshot_id (v2)
run_snapshot        run_id, column_id, prompt_version_id, instructions_version_id
run_coverage        run_id, dimension_key           (ticked test-set dimensions)
coverage_dimension  key, label, position, requires_grouping   (seeded, 14 rows)
eval_result         id, run_id, column_id, test_document, prompt_version, actual_answer,
                    evidence_relied_on, expected_behavior, passed, failure_class, error_type,
                    revision_note, rerun_scope, result_after_rerun, regressions, created_at
memo_outline        id, matter_id, name, version, created_at, is_current
memo_section        id, outline_id, name, position
memo_assertion      id, section_id, text, position, kind('extraction'|'judgment'), note
assertion_source    id, assertion_id, column_id, note
provenance          id, entity_type, entity_id, action, source_type, actor, at, detail(json)

-- schema v2 (Addendum A.1)
matter              + vault_project_id
review_table        + vault_project_id            (overrides the matter's)
document_set_snapshot  id, matter_id, vault_project_id, observed_at, ready_count,
                    latest_uploaded_at, set_hash, file_ids(json), source('harvey_api'|'manual'),
                    note, created_at
```

Versioning: `v{major}.{minor}`. Ingest assigns `v1.0`; `column_revise` increments minor
(`bump="major"` available). Re-ingest of an existing table matches by (table, column name):
unchanged text = no new version; changed text = new minor version; new name = new column;
missing name = reported as `COLUMN_ABSENT_FROM_INGEST` finding, never auto-retired.

Dependencies: `intra_table_ref` edges are rebuilt from `@Column` references every time a
column's prompt changes. `cross_table_parameter` edges are rebuilt from bindings every time
`parameter_set` runs (source column → each consuming column; table-level bindings fan out to
every active column in the consuming table). `advisory` edges are declared by the user on a
column record and only ever touched explicitly.

Freshness (v2): a run links the latest document-set snapshot for its table's vault project,
or records a manual one from `documents_ready`. Per table the state is `unobserved` (no
snapshot), `never_run`, `unrecorded` (the run has none), `current`, or `moved` (count,
latest upload, or file-id set differs). Reverse coverage: `impact_of_change`,
`staleness_report`, and `freshness_check` end with the memo assertions whose sources are
affected (`unsupported` when all active sources are, `weakened` when some are).

## 3. The three areas that need care

**Impact and staleness.** One directed graph over all columns in a matter, all three edge
kinds, across tables. `impact_of_change` does a visited-set traversal (cycle-safe), labels each
hit `direct` (edge from the subject) or `transitive`, then orders the affected set with Kahn's
algorithm; if a cycle prevents a full order the remainder is appended in traversal order and a
`GRAPH_CYCLE` finding is attached. Staleness per column: `never_run`; `direct` when the
current prompt version, the table's current instructions version, or a bound parameter's
`resolved_at` post-dates the column's last run; `transitive` when any transitive upstream
column is stale or has a version newer than this column's last run.

**Validation.** Vocabulary exactly `Not addressed`, `Not stated`, `Not applicable`,
`Incorporated terms`, `Unable to determine`; synonyms `N/A`, `None`, `Unclear`, `Silent`,
`Unknown`, `TBD`. Typed columns = Date, Number, Currency, Duration. Limits 10,000 hard /
6,000 advisory. Failure taxonomy is the skill's nineteen classes. Coverage dimensions are the
template's fourteen.

**Coverage.** Assertions carry `kind` (required): `extraction` → gap when unsourced;
`judgment` → reported as a boundary, never a gap. Reliability: a source column is reliable
when it has a recorded run, no open failure (latest result per test document failed), is not
stale, and its table's latest run ticks every applicable dimension. An assertion is
`reliably_covered` if any source is reliable, else `nominally_covered` with the reasons per
column. Unsourced active columns are listed. A judgment assertion mapped to columns is
reported with those columns as evidence inputs, not as coverage.

## 4. Finding codes

Prompt lint: `PROMPT_LENGTH_HARD`, `PROMPT_LENGTH_ADVISORY`, `FALLBACK_SYNONYM`,
`FALLBACK_NOT_STATED_UNTYPED`, `FALLBACK_NOT_ADDRESSED_TYPED`, `CLASSIFY_LABEL_NOT_CONFIGURED`,
`CLASSIFY_QUALIFIER_PERMITTED`, `REF_UNRESOLVED`, `REF_FORWARD`, `REF_SELF`,
`OUTPUT_CONTRACT_MISSING`, `MARKDOWN_IN_CELL`, `CHARACTER_COUNT_RULE`, `DEAD_REFERENCE`.

Ingest: `NATIVE_TYPE_MISSING`, `NATIVE_TYPE_INVALID`, `OPTIONS_MISSING`, `OPTIONS_MALFORMED`,
`OPTIONS_ON_NON_CLASSIFY`, `POSITION_DUPLICATE`, `COLUMN_ABSENT_FROM_INGEST`,
`ADVISORY_REF_UNRESOLVED`.

Standard: `STANDARD_CONTRADICTS_FIRM`, `STANDARD_VOCABULARY_NOT_SKILL`.

Graph: `GRAPH_CYCLE`, `ROLE_ORDER_VIOLATION`, `CONTROL_PLANE_NARRATIVE`, `PARAM_ORPHANED`,
`PARAM_UNRESOLVED_CONSUMED`, `PARAM_NOT_BOUND_TO_INSTRUCTIONS`,
`PARAM_VALUE_ABSENT_FROM_INSTRUCTIONS`, `PARAM_VALUE_ABSENT_FROM_PROMPT`,
`PARAM_SOURCE_RETIRED`, `BINDING_DANGLING`, `DEPENDENCY_ON_RETIRED`.

Consistency: `DATE_PATTERN_DIVERGENT`, `CURRENCY_PATTERN_DIVERGENT`, `ENTITY_NAME_VARIANT`,
`CONCEPT_DIVERGENT_RULES`, `CONCEPT_NAME_VARIANT`, `INSTRUCTIONS_MISSING`,
`INSTRUCTIONS_VOCABULARY_INCOMPLETE`.

Evaluation: `FAILURE_CLASS_INVALID`, `ERROR_TYPE_INVALID`, `PROMPT_VERSION_MISMATCH`,
`RUN_TABLE_MISMATCH`.

Coverage: `COV_EXTRACTION_GAP`, `COV_JUDGMENT_BOUNDARY`, `COV_NOMINAL_ONLY`,
`COV_UNSOURCED_COLUMN`, `COV_SOURCE_RETIRED`, `COV_DIMENSION_UNTICKED`, `MEMO_ASSERTION_AT_RISK`.

Freshness (Addendum A.1): `DOCSET_MOVED`, `DOCSET_UNRECORDED`, `DOCSET_UNOBSERVED`,
`DOCSET_NO_PROJECT`, `HARVEY_UNAVAILABLE`. Readiness (A.4): `COLUMN_NOT_VERIFIED`, `COLUMN_STALE`,
`COLUMN_NEVER_RUN`, `OPEN_FAILURE`, plus the codes of the checks it composes.

## 5. Layout

```
src/prompt_graph/
  server.py        FastMCP tool definitions (docstrings for the model), name resolution
  db.py            connection, WAL, migrations
  constants.py     vocabulary, taxonomy, dimensions, native types
  findings.py      Finding
  lint.py          prompt_check rules
  refs.py          @Column parsing
  service.py       matter / standard / ingest / revise / parameters / read
  graph.py         dependency graph, impact, cycles, staleness
  checks.py        suite_check (graph + consistency)
  evaluation.py    runs, eval results, failures, compare
  coverage.py      memo outline + coverage + reverse coverage (column -> assertions)
  freshness.py     document-set snapshots, freshness map and findings
  harvey.py        Vault API client (stdlib, injectable fetcher, 5-minute cache)
  readiness.py     table_readiness composition
  export.py        matter_export
  seed.py          demo matter fixture (Project Harbor, 4 tables)
tests/             one file per area + validation rules + idempotency + cycles + addendum
```
