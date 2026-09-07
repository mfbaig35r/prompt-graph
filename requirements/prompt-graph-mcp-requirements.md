# prompt-graph — MCP Server Requirements

**Server name:** `prompt-graph` (MCP identifier), "Prompt Graph" in user-facing text.
**Companion to:** `legal-review-table-builder` skill (v1, packaged as `legal-review-table-builder.skill`)
**Purpose of this document:** scaffolding input for Fable, then implementation input for Claude.
**Status:** requirements, pre-scaffold. Open questions in §12 should be answered before or during scaffolding.

**Name check (2026-09):** `prompt-graph` has no conflict in legal tech. The only prior uses found are an arXiv paper on prompt sanitization and two small GitHub repositories applying LLMs to geometric and graph problems — none of which your users will encounter. Verify `prompt-graph` on npm and PyPI before publishing anything under that identifier.

---

## 1. Why prompt-graph exists

The `legal-review-table-builder` skill handles design judgment well: it decides what a column should ask, how to scope it, which fallback state applies, and how to diagnose a failed output. That work should stay in the skill.

What the skill cannot do is hold state, compute reliably, or see across tables. Three specific gaps drive this build.

**Scale.** A single M&A diligence matter runs roughly twelve review tables averaging thirty columns — about 360 prompts serving one analytical goal. The skill currently reasons over one table at a time because that is all that fits in a working session. Consistency across the full suite is therefore unverified.

**Cross-table dependency is invisible to the platform.** Harvey's `@Column` reference works within a table only. But an entity table that resolves exact legal names is a real upstream input to the charter, real estate, and contracts tables. That dependency exists, is load-bearing, and is currently tracked nowhere. When the entity table changes, nothing tells anyone which of the other eleven tables just went stale.

**Correct is not the same as sufficient.** The skill's `evaluation.md` tests whether a column returns the right answer. It does not test whether the resulting table set can support the deliverable. Every column can pass and the diligence memo can still be undraftable. Nothing currently detects that.

The server fills these three gaps and nothing else.

---

## 2. Division of responsibility

This is the governing design principle. Violating it will produce a technically correct server that no one at the firm can use.

| Layer | Owns | Example |
| --- | --- | --- |
| **Skill (methodology)** | Design judgment, prompt drafting, failure diagnosis, revision strategy, the controlled fallback vocabulary, platform capability facts | "This column conflates authorized capital with issued interests; split it." |
| **Claude (Opus, orchestration)** | Reading messy input, normalizing it, deciding what to call, interpreting findings, explaining consequences to the user, drafting revisions | Reads an Excel export, extracts column records, calls ingest, reads back findings, explains what they mean |
| **prompt-graph (state + determinism)** | Storage, versioning, graph computation, deterministic validation, coverage arithmetic | "Column 40's fallback set diverges from the matter standard. Changing `Target Legal Name` marks 47 columns across 6 tables stale." |

Two rules follow.

**Tools are attorney-level verbs, not CRUD over the data model.** A paralegal must never have to call `column_upsert`, then `dependency_add`, then `graph_validate` to accomplish one thing. If a workflow requires chaining three primitives, that workflow is one tool.

**Tools return findings, not verdicts.** A finding is a factual observation with a stable code and a subject. It does not contain advice, severity rhetoric, or a recommended rewrite. Claude turns the finding into an explanation in the skill's voice. This keeps legal judgment with the model and out of hardcoded strings, and it means server output never has to be re-litigated when firm practice changes.

Server output that is shown to a user should be attorney-readable in tone. No raw JSON dumps in the final response, no internal IDs surfaced unless the user asked for them.

---

## 3. Users and access

**Primary users:** attorneys and paralegals with no technical background, working inside the Claude app.
**Secondary user:** the author, doing suite design and maintenance.

Design implication: every tool must be usable via natural-language request routed through Claude. No user should need to know the data model, the tool names, or the difference between a version and a run.

**Confidentiality.** Prompts, Table Instructions, entity lists, and matter objectives contain client-confidential information. The database is therefore a client data store, not a config file. Access control, storage location, and retention need a firm answer before this holds live matter data — see §12.

---

## 4. Scope

### In scope

- Ingesting review table schemas and prompts from flexible sources
- Canonical storage with prompt versioning and change history
- Intra-table and cross-table dependency graph
- Shared matter parameters and their propagation
- Staleness computation across the full suite
- Deterministic prompt and schema validation
- Consistency checking against a firm and matter standard
- Evaluation logging, failure classification, and regression comparison
- Memo coverage analysis and gap reporting

### Out of scope (v1)

- **Drafting or revising prompts.** The skill does this. The server never generates prompt text.
- **Making legal determinations.** Preserved directly from the skill's human validation boundary.
- **Parsing files.** Claude reads Excel, CSV, and exports. The server receives structured records only.
- **Executing Harvey runs.** Deferred to Phase 4, pending §12.
- **Replacing the skill's reference material.** `prompt-patterns.md`, `worked-examples.md`, `evaluation.md`, and `platform-adaptation.md` stay in the skill. Do not port them into MCP resources.

---

## 5. Ingest model

Input is flexible; storage is canonical.

**Accepted paths:** prompts pasted into chat; an Excel workbook or CSV; a Harvey table export; prompts Claude has just drafted in-session.

**The server does not parse any of these.** Claude reads the source, extracts the fields, and submits normalized records. This keeps messy interpretation with Opus — where it belongs — and means the ingest tool has one stable contract regardless of source.

**Normalized column record:**

```
name                 required
position             required (integer, order within table)
native_type          required (Classify|Date|Currency|Number|Duration|Verbatim|FreeResponse)
configured_options   required if native_type = Classify (ordered list, UI order)
prompt_text          required
purpose              optional (one attorney-readable sentence)
upstream_refs        optional (list of @Column names, as written)
status               optional, default 'draft'
```

**Server responsibilities on ingest:** validate record shape; reject or flag missing native types; resolve `@Column` references to stored column IDs and flag unresolved ones; assign version `v1.0` to each prompt; record provenance (source type, timestamp, ingesting user).

Ingest is idempotent-ish by design: re-ingesting an existing table creates new prompt versions for changed columns rather than duplicating columns. Matching is by table plus column name; a rename must be an explicit operation, not an inferred one.

---

## 6. Data model

SQLite, single file, WAL mode. Schema below is indicative, not prescriptive — Fable should refine.

**`standard`** — firm baseline plus per-matter overlay.
`id, scope ('firm'|'matter'), matter_id (null for firm), fallback_vocabulary (json), naming_rules, date_pattern, currency_pattern, default_evidence_boundary, version, created_at`

A matter standard **extends** the firm standard; it may add entity names, objective, and matter-specific conventions. It may not contradict the firm baseline — attempted contradictions surface as findings, not silent overrides. This gives consistency checks a stable reference.

**`matter`** — `id, name, objective, side (buy|sell), standard_id, created_at, status`

**`review_table`** — `id, matter_id, name, review_unit, platform, grouping_enabled, max_docs_per_unit, stage, position`

**`table_instructions`** — versioned, since Harvey exports omit them and this store is authoritative.
`id, table_id, version, text, created_at, change_note`

**`column`** — `id, table_id, name, position, native_type, configured_options (json), purpose, status (draft|testing|verified|retired)`

**`prompt_version`** — `id, column_id, version, text, created_at, change_note, failure_class_addressed, is_current, char_count`

**`dependency`** — `id, from_column_id, to_column_id, kind, declared_by, note`
`kind` ∈ `intra_table_ref` (a real Harvey `@Column`), `cross_table_parameter` (mediated by a shared parameter), `advisory` (a real analytical dependency Harvey cannot express).

The distinction matters: `intra_table_ref` is enforceable by the platform, the other two are not and must be maintained by convention. Findings should say which kind is at issue.

**`shared_parameter`** — the cross-table mechanism.
`id, matter_id, name, value, source_column_id (nullable), source_table_id, resolved_at, status (unresolved|resolved|contested)`

Example: `Target Legal Name` resolved from the entity table's principal-subject column, consumed by six downstream tables via their Table Instructions.

**`parameter_binding`** — `id, parameter_id, consuming_table_id, consuming_column_id (nullable), binding_site ('table_instructions'|'column_prompt')`

**`run`** — `id, table_id, started_at, note` plus a snapshot mapping each column to the prompt version executed. Staleness depends on this snapshot.

**`eval_result`** — mirrors the skill's `evaluation-log-template.csv` exactly, so existing logs import cleanly.
`id, run_id, column_id, test_document, prompt_version, actual_answer, evidence_relied_on, expected_behavior, passed (bool), failure_class, error_type, revision_note, rerun_scope, result_after_rerun, regressions`

`failure_class` is a closed enum drawn from the skill's taxonomy: `scope_leakage`, `concept_conflation`, `document_type_error`, `temporal_status_error`, `evidence_overstatement`, `holder_direction_error`, `silence_uncertainty_error`, `output_format_error`.

**`coverage_dimension`** — the test-set checklist from `evaluation.md`, tracked per table so an unticked dimension reads as open risk rather than a pass.

**`memo_outline`** / **`memo_assertion`** / **`assertion_source`** — see §9.

---

## 7. Tool surface

Roughly nineteen tools in seven groups. Names below are working names; final naming should read as attorney-legible verbs.

### Matter and standard

1. **`matter_open`** — create or open a matter; returns matter context including tables, column counts, unresolved parameters, and staleness summary. First call in most sessions.
2. **`standard_set`** — define or amend the firm baseline or a matter overlay. Returns findings if a matter overlay contradicts the baseline.

### Ingest

3. **`table_ingest`** — accept a table plus normalized column records (§5). Returns per-record findings: unresolved refs, missing types, malformed options, char-limit breaches.
4. **`table_instructions_set`** — store versioned Table Instructions for a table.

### Inspection

These exist so Claude can query rather than hold 360 prompts in context. This is the main practical benefit of persistence.

5. **`matter_overview`** — suite-level state: tables, stages, column status counts, stale columns, open failures, unresolved parameters.
6. **`columns_find`** — filter by table, type, status, failure class, consumed parameter, or staleness. Returns summaries, not full prompt text.
7. **`column_read`** — one column in full, optionally with version history and change log.

### Graph and impact

8. **`impact_of_change`** — given a column or parameter, return everything downstream that requires rerun, in dependency order, **across tables**. This is the tool that makes a twelve-table suite maintainable.
9. **`graph_check`** — cycles, unresolved `@Column` references, ordering violations (detail column sequenced before its orientation column), orphaned parameters, dangling bindings.
10. **`staleness_report`** — columns whose current prompt version differs from the version in their last run, or whose upstream input has changed since. Distinguishes *directly* stale from *transitively* stale.

### Validation

11. **`prompt_check`** — deterministic lint on prompt text. Callable pre-ingest so Claude can check a draft before storing it. Rules in §8.
12. **`consistency_check`** — cross-table divergence from the matter standard: fallback vocabulary drift, inconsistent date or currency patterns, an entity named differently in different tables, the same concept extracted under two different column names.

### Parameters

13. **`parameter_resolve`** — record a resolved shared parameter and its source column.
14. **`parameter_bindings`** — list consumers of a parameter.
15. **`propagation_preview`** — given a parameter change, show which Table Instructions and column prompts reference the old value and need updating. Preview only; the server does not rewrite prompt text.

### Evaluation

16. **`run_record`** — open a run and snapshot the prompt versions executed.
17. **`eval_record`** — log per-document results; accepts batch entry so a full test set is one call.
18. **`failures_summary`** — group open failures by class, table, or column; surfaces systematic problems that single-column review misses.
19. **`run_compare`** — diff two runs of a column across the same test documents. Returns fixed, still-failing, and newly-failing — the regression detection Harvey lacks.

### Coverage

20. **`memo_outline_set`** — store the target deliverable's sections and required assertions.
21. **`coverage_check`** — the sufficiency test (§9).

---

## 8. Deterministic validation rules

These are currently stated as instructions in the skill and enforced only by model attention. Moving them to code makes them reliable and frees the model's attention for judgment.

**Prompt-level (`prompt_check`):**

- Character count against Harvey limits: **hard fail above 10,000**, **advisory above 6,000**.
- Fallback vocabulary: only `Not addressed`, `Not stated`, `Not applicable`, `Incorporated terms`, `Unable to determine`. Flag synonyms — `N/A`, `None`, `Unclear`, `Silent`, `Unknown`, `TBD`.
- `Not stated` used outside a Date, Number, Currency, or Duration column, or `Not addressed` used inside one.
- Classify columns: any output label in the prompt that is not in the configured option set; any instruction permitting a qualifier after an em dash (allowed only in Free Response).
- Unresolved `@Column` references, and references to a column positioned later in the same table.
- Output-contract presence: a prompt with no stated output format.
- Markdown-in-cell risk: instructions that permit Markdown in the returned answer without an explicit output contract allowing it.

**Schema-level (`graph_check`, `consistency_check`):**

- Dependency cycles.
- Ordering violations against the skill's staged pattern (orientation → conditional extraction → validation → reconciliation → human review).
- A narrative Free Response column acting as the control plane for multiple downstream columns — the skill warns against this explicitly.
- Two columns in different tables extracting the same concept under divergent names or fallback rules.
- A shared parameter consumed by a table that never binds it into its Table Instructions.

**Finding format:** `{code, subject_type, subject_id, subject_name, observation, evidence}`. `observation` is one factual sentence. No advice, no severity adjectives, no suggested rewrite. Claude supplies interpretation.

---

## 9. Memo coverage — the sufficiency test

This capability does not exist in the skill and is the highest-value addition after the cross-table graph.

**Problem:** the review tables are an intermediate artifact. The deliverable is a diligence memo. An attorney does not care whether column 27 passed; they care whether they can write the change-of-control section. Column-level evaluation cannot answer that.

**Method — invert the analysis.** Start at the memo, not the table.

1. **Capture the target.** `memo_outline_set` stores the memo's sections and, under each, the assertions the memo must be able to make. For M&A diligence: capitalization and ownership, change-of-control triggers, consents and approvals required, encumbrances, material contract terms, litigation and compliance status, and so on.

2. **Trace each assertion to sources.** Each assertion is mapped to the columns that would supply its evidence. Claude proposes the mapping using the skill's judgment; the server stores and audits it.

3. **Report gaps in two distinct flavors.** This distinction is essential and must not be collapsed:

   - **Extraction gap** — the assertion needs document evidence that no column currently captures. This is a schema defect. Fix by adding or revising a column.
   - **Judgment boundary** — the assertion requires a determination the tables should deliberately *not* make: validity, enforceability, operative status, deal consequence. This is correct behavior, not a defect. It is flagged so the memo plan shows where attorney input is required, and so no one later "fixes" it by asking a column to make a legal conclusion.

   A third case is worth reporting: **unsourced extraction** — a column that feeds no assertion. Either the memo outline is incomplete or the column is unnecessary. Both are worth knowing before running 360 prompts across a document set.

4. **Weight by reliability.** An assertion sourced only from columns with open failures or an unticked coverage dimension is *nominally* covered but not *reliably* covered. Report those separately.

**Output:** a gap report an attorney can read before diligence begins — what the suite will support, what it will not, and where they must supply judgment themselves.

---

## 10. Harvey integration (Phase 4)

Deferred, and possibly smaller than it looks.

A Harvey connector already exists in the Claude app. **Before building any Harvey I/O, inventory that connector's tool surface.** If it already exposes table read, prompt write, or rerun triggers, this server should compose with it rather than duplicate it — meaning this server holds inventory, graph, and coverage, and delegates execution.

If direct integration is built, the target capabilities are: read live table schema, push revised prompts, trigger scoped column reruns, and pull run outputs directly into `eval_record`. That last one closes the loop — evaluation stops being manual transcription.

Note the skill's own caution: `platform-adaptation.md` carries a *Last verified* date because Harvey's capabilities move. Any integration should fail loudly on unexpected API shape rather than silently assuming a stale capability model.

---

## 11. Build phases

Each phase is independently useful. Do not defer usefulness to the end.

- **P0 — Storage and lint.** SQLite schema, `matter_open`, `standard_set`, `table_ingest`, `table_instructions_set`, `column_read`, `columns_find`, `prompt_check`. Delivers: canonical inventory with real versioning, plus deterministic lint. Immediately better than hand-maintained Markdown.
- **P1 — Graph and staleness.** `impact_of_change`, `graph_check`, `staleness_report`, parameter tools, `consistency_check`, `matter_overview`. Delivers: the twelve-table suite becomes maintainable. This is the core value.
- **P2 — Evaluation.** `run_record`, `eval_record`, `failures_summary`, `run_compare`. Delivers: regression detection Harvey does not provide.
- **P3 — Coverage.** `memo_outline_set`, `coverage_check`. Delivers: the sufficiency test.
- **P4 — Harvey I/O.** Per §10.

---

## 12. Open questions

To be answered before or during scaffolding.

1. **Deployment and concurrency.** SQLite on a network share, or a centrally hosted server? If multiple attorneys open the same matter, WAL mode handles concurrent reads but not coordinated edits. This affects whether the server is stdio-local or hosted.
2. **Access control and confidentiality.** Matter data is client-confidential. Who can open which matter? Is there a retention or deletion requirement? Does this need to sit inside existing firm document-management controls?
3. **Harvey connector surface.** What does the existing connector actually expose? Determines the size of P4.
4. **Editing outside Claude.** If someone edits a prompt directly in Harvey's UI, the inventory silently drifts. Is there a reconciliation path, or is the inventory authoritative by policy?
5. **Firm standard authorship.** Who owns the firm baseline, and how is it amended? A per-matter overlay that quietly contradicts the baseline defeats consistency checking.
6. **Memo outline reuse.** Are diligence memo outlines standardized enough to ship as templates, or does each deal define its own?

---

## 13. Changes to the existing skill

The skill remains the methodology layer and is not replaced. Three additions:

1. **A new operating mode — `Orchestrate`** — for suite-level work across multiple tables, covering when to call the server and how to present findings.
2. **Tool-awareness in the working behavior section** — check the inventory before redesigning; record versions on revision; run `impact_of_change` before declaring a rerun scope.
3. **Template deprecation, carefully.** `assets/prompt-inventory-template.md` and `assets/evaluation-log-template.md` become fallbacks for when the server is unavailable, not the primary path. Keep them; the skill must still work standalone.

**Packaging note:** the distributed zip contains a flat copy of the reference files alongside the `.skill` bundle. In that flat copy the relative links (`references/workflow.md`, `assets/prompt-inventory-template.md`) do not resolve. Only the `.skill` bundle has correct structure. Distribute the bundle, or fix the loose folder's directory layout.
