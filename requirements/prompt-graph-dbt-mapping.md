# dbt → prompt-graph

**Purpose:** a working mental model, and a gap list. Mapped against `prompt-graph-mcp-requirements.md` §6–§9.

**Revised 2026-09-15.** The original gap list has been built out: five of the six items in §4 shipped, including the one §7 said to do first. This revision records what closed, corrects §5 (which argued against something since built and demoed), and adds the two disanalogies that only became visible once the system was substantially complete. Measurements against the live database: 832 active columns, 716 dependencies, 2 matters.

---

## 1. Why the analogy holds

dbt's real insight was never SQL templating. It was that a pile of transformations nobody could reason about becomes tractable once you have four things: a dependency graph, version control, tests that gate promotion, and lineage you can query. Everything else in dbt is scaffolding around those four.

You have the same problem shape. Hundreds of prompts, cross-file dependencies nobody tracked, no way to know what breaks when one thing changes, and a downstream deliverable that silently degrades when an upstream input shifts. That is the pre-dbt analytics team almost exactly.

### 1.1 Three of the four pillars are built

Worth scoring honestly, because the missing one is not an accident of sequencing.

| Pillar | State |
| --- | --- |
| Dependency graph | Built. `dependency`, 716 edges, two kinds |
| Version control | Built. `prompt_version`, `run_snapshot` pins what executed |
| Queryable lineage | Built. `impact_of_change`, `staleness_report`, and a UI |
| **Tests that gate promotion** | **Not built, and structurally expensive** |

In dbt, `dbt test` runs in seconds against the warehouse, which is what lets it gate every commit. Cheapness is the feature. Here an evaluation needs attorney labelling and Harvey calls at 20 per minute, and `eval_result` stores no expected answer, so a score cannot even be recomputed after a prompt changes (see `prompt-graph-eval-design.md`).

So the pillar dbt leans on hardest is the one this system has the most trouble affording. That reframes the evaluation work: it is not an enhancement sitting beside the graph work, it is the missing leg of the thing being claimed.

## 2. Where it breaks

Four structural disanalogies. Each one tells you which dbt features to skip.

**dbt is deterministic. Prompts are not.** In dbt, if the model compiles and the tests pass, it passes for the same reason every time. Your `run_compare` and `eval_result` layer exists to handle something dbt never has to: a prompt that passed yesterday failing today with no change to the prompt. This is why evaluation is more load-bearing in prompt-graph than testing is in dbt, and why anything dbt does that assumes deterministic rebuild doesn't port.

**dbt executes the DAG. prompt-graph doesn't.** dbt is a modeling layer *and* an orchestrator. You are only the modeling layer: Harvey executes. So every dbt feature about *how* to materialize, when to run incrementally, or how to schedule is inert for you.

**dbt's tests are cheap. Yours are not.** §1.1. The consequence is that dbt's build-gate posture ("nothing reaches production untested") cannot be adopted wholesale, because the test is the scarce resource rather than the build. What ports is tiering: a cheap check on every change, an expensive one per release.

**In dbt the model is the deliverable. Here it is two layers away.** A dbt model materializes as a table someone queries. A prompt-graph column produces a cell in Harvey, which a human reads to write a memo. Nothing stored here is consumed by anyone directly. That is precisely why correlation carries far more weight here than exposures do in dbt: it is the only thing tying the modeled layer to the artifact anyone actually wants.

The clean framing, updated: **prompt-graph is dbt's modeling, governance and lineage layer, minus orchestration, plus an evaluation layer dbt doesn't need, plus a requirement register dbt has no concept of.**

---

## 3. Feature map

| dbt | prompt-graph equivalent | Status |
|---|---|---|
| **Model** | Column prompt | Built — `column` + `prompt_version` |
| **`ref()`** | Harvey `@Column` | Built — `dependency.intra_table_ref` |
| **`ref()` across projects** | Cross-table dependency | Built — `cross_table_parameter`; this is the core value |
| **`source()`** | The documents under review | Built — `document_set_snapshot`, `run.document_set_snapshot_id` |
| **Source freshness** | New/amended docs in the data room since last run | Built — `freshness_check`, `DOCSET_*` findings |
| **Seeds** | Firm standard, controlled fallback vocabulary | Built — `standard` |
| **Vars / macros** | Shared parameters | Built — `shared_parameter`, `parameter_binding` |
| **Snapshots** | Prompt version history | Built — `prompt_version`; `run_snapshot` pins executed versions |
| **Generic data tests** | Deterministic lint applied to every prompt | Built — `prompt_check` §8 |
| **Singular data tests** | Per-column expected behavior on a test doc | Partial — `eval_result` exists, never run, and stores no expected answer |
| **Unit tests (fixtures)** | Test document set with known expected answers | **Gap** — see `prompt-graph-eval-design.md` |
| **Model contract** | Native type + configured options + fallback set, enforced pre-store | Built — `prompt_check` pre-ingest is contract-at-build-time |
| **Test selection (`--select`)** | `suite_check` families | Built — six: prompts, graph, parameters, consistency, coverage, requirements |
| **Model versions (coexisting v1/v2)** | — | Skip — see §5 |
| **Exposures** | The diligence memo | Built — `memo_outline`, `assertion_source`, and the reverse traversal (§4.1) |
| **Semantic layer** | Concept consistency across tables | Built, under another name — see §5 |
| **Lineage graph / docs site** | The read API and UI | Built — five pages, a layered DAG, a glossary and a guide |
| **`state:modified` / `--select +model+`** | `impact_of_change`, `staleness_report` | Built — your strongest area |
| **Artifacts (`manifest.json`)** | `matter_export` | Built |
| **Packages / dbt hub** | Reusable table templates per deal type | **Gap** — the only one left, see §4.5 |
| **Model access, groups** | Firm baseline vs matter overlay | Built — `standard.scope` |
| **Environments (dev/prod)** | `column.status` draft → testing → verified | Built |
| **Slim CI / build gate** | `table_readiness` | Built |
| **Descriptions / doc blocks** | `column.purpose` | Built |
| **`persist_docs`** | Push `purpose` into Harvey's column description | Dead — the API cannot write column definitions |
| **— (no equivalent)** | **Requirement register** | Built — see §3.1 |
| **Materializations, incremental, semantic layer runtime** | — | N/A — no execution layer |

### 3.1 The thing dbt has no concept of

dbt exposures declare that a dashboard consumes a model. Nothing in dbt declares **the external specification the warehouse was built to satisfy**, and so nothing in dbt can tell you about a model you never built. A requirement that maps to no model produces no node, no test and no artifact; it lives in a product doc nobody linked to the DAG.

`requirement`, `requirement_part`, `requirement_source` and `requirement_link` record exactly that, and the disposition that matters most is the one where a playbook prompt resolves to **no table at all**. That is a stored finding here and an absence everywhere else.

This is the one place prompt-graph is not a port of dbt but an extension past it, and it is worth saying plainly when explaining the system to someone who knows dbt well.

---

## 4. Worth stealing: what happened

The original ranking, with outcomes.

### 4.1 Exposures, run backward: BUILT

The ask was a reverse traversal over `assertion_source`, folded into `impact_of_change` so a change report ends with memo consequences rather than stopping at columns.

Shipped, and wider than specified: `assertions_for_columns` and `memo_findings` are wired into `impact_of_column`, `impact_of_parameter` **and** `staleness_report`. So the question "which memo assertions are now unsupported" is answered for a prompt change, a parameter change, and drift alike. The column detail view surfaces it per column.

### 4.2 Source freshness: BUILT

Called out as the gap to worry about most, because it was invisible: a column could be verified, unstale and passing every eval while being wrong, having been run against 400 documents when there are now 460.

Shipped as `freshness_check` over `document_set_snapshot`, with `DOCSET_MOVED`, `DOCSET_UNRECORDED`, `DOCSET_UNOBSERVED` and `DOCSET_NO_PROJECT`. The Vault enumeration path carries a request budget so a rate limit degrades into a partial answer with a stated reason rather than a retry loop.

### 4.3 Manifest export: BUILT

`matter_export`, one JSON document, `export_format_version: 1`. The defensibility argument in the original still stands and is the reason to keep it stable rather than convenient.

### 4.4 A lineage view: BUILT, and further

The original proposed keeping it out of the server and having Claude render the graph in chat. That was under-ambitious. There is now a read-only HTTP layer and a UI: overview, requirements, correlation, consistency and per-module pages, with a layered DAG, a glossary and a guide.

The prediction held. For non-technical users the picture is what converts the tool from tolerated to trusted.

### 4.5 Packages: STILL OPEN, and now the live question

Promote a verified table out of a finished matter into a firm-level template that seeds the next one.

This was deliberately deferred as post-P3 and it is the only §4 item outstanding. It has stopped being theoretical: "what would it take to register all of this for a domain other than M&A" is the same feature asked from the other end, and there are now two matters to generalize across rather than one.

The schema caution from the original was honoured: nothing hard-binds `review_table` or `column` to a matter in a way that makes promotion painful. The door is still open.

### 4.6 A build gate: BUILT

`table_readiness` composes the checks. Note the §2 caveat: it composes the *cheap* checks. It cannot gate on evaluation, because evaluation is expensive and has never been run, so "ready" currently means "well-formed", not "known to work". Worth being precise about that in any attorney-facing description.

---

## 5. Deliberately don't steal

**Model versions (coexisting v1 and v2).** dbt supports this because different consumers migrate at different speeds. Your consumer is one memo. Version history yes, concurrent live versions no.

**Materializations, incremental models.** Execution concepts. Harvey's.

**~~Semantic layer / metrics.~~ CORRECTED.** The original said to skip this because "you have one deliverable." That reasoning was wrong, and the feature was built anyway under a different name.

The semantic layer does not solve *multiple deliverables*, it solves *multiple definitions of one concept*. prompt-graph has that problem acutely: the same legal question asked in several modules, answered from a different menu each time. dbt acquires it from multiple BI tools; you acquire it from multiple authors over time. Same disease, different vector.

It shipped as the `consistency` family (`CONCEPT_NAME_VARIANT`, `CONCEPT_DIVERGENT_RULES`, `CURRENCY_PATTERN_DIVERGENT`) and the Consistency page, and on the live corpus it found 19 real clusters. Keep the general lesson: when a dbt feature looks inapplicable, check whether the *problem* it solves is absent, not whether dbt's *framing* of it matches.

**dbt's severity levels (`warn` vs `error`).** Still correct to skip, and it remains the sharpest expression of the difference between the two systems. Severity is a legal judgment about a specific matter: an inconsistent date format is trivial in one table and serious in another. Report the finding with its evidence; let the attorney weigh it. This is the findings-not-verdicts posture, and it is why `eval_result.passed` is worth re-examining (`prompt-graph-eval-design.md` §E.9.3): it is the one stored verdict in a system that otherwise refuses to issue them.

---

## 6. Crib sheet

| dbt | prompt-graph |
|---|---|
| model | column prompt |
| project | matter |
| `ref()` | `@Column` / dependency |
| source | data room document set |
| source freshness | `freshness_check` |
| exposure | memo assertion |
| semantic layer | concept consistency |
| test | eval |
| `--select` | `suite_check` family |
| manifest | matter export |
| package | deal-type table template *(not built)* |
| *(no equivalent)* | requirement register |

---

## 7. If you act on one thing

Previously source freshness. That is done.

**Now: store the expected answer.** §1.1 is the argument. Three of dbt's four pillars are built and the fourth is missing, and the reason it is missing is that `eval_result` records a human's boolean without recording what correct meant, so nothing can be re-scored and every prompt revision costs attorney time again. Until that changes, "tests that gate promotion" stays aspirational and the dbt comparison is three-quarters earned.

It is also the cheapest of the remaining items and the only one that cannot be retrofitted, because retrofitting means re-labelling.

**A note on the pitch.** "dbt for legal" is a good line and a slightly dangerous one with a technical audience, because everyone who hears dbt thinks orchestrator, and prompt-graph never executes anything. Say the modeling and governance layer, and that the warehouse is Harvey.
