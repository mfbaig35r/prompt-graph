# dbt → prompt-graph

**Purpose:** a working mental model, and a gap list. Mapped against `prompt-graph-mcp-requirements.md` §6–§9.

---

## 1. Why the analogy holds

dbt's real insight was never SQL templating. It was that a pile of transformations nobody could reason about becomes tractable once you have four things: a dependency graph, version control, tests that gate promotion, and lineage you can query. Everything else in dbt is scaffolding around those four.

You have the same problem shape. 360 prompts, cross-file dependencies nobody tracked, no way to know what breaks when one thing changes, and a downstream deliverable that silently degrades when an upstream input shifts. That is the pre-dbt analytics team almost exactly.

## 2. Where it breaks

Two structural disanalogies. Both matter, because each one tells you which dbt features to skip.

**dbt is deterministic. Prompts are not.** In dbt, if the model compiles and the tests pass, it passes for the same reason every time. Your `run_compare` and `eval_result` layer exists to handle something dbt never has to: a prompt that passed yesterday failing today with no change to the prompt. This is why evaluation is more load-bearing in prompt-graph than testing is in dbt, and why anything dbt does that assumes deterministic rebuild doesn't port.

**dbt executes the DAG. prompt-graph doesn't.** dbt is a modeling layer *and* an orchestrator. You are only the modeling layer — Harvey executes. So every dbt feature about *how* to materialize, when to run incrementally, or how to schedule is inert for you.

The clean framing: **prompt-graph is dbt's modeling, governance, and lineage layer, minus orchestration, plus an evaluation layer dbt doesn't need.**

---

## 3. Feature map

| dbt | prompt-graph equivalent | Status |
|---|---|---|
| **Model** | Column prompt | Built — `column` + `prompt_version` |
| **`ref()`** | Harvey `@Column` | Built — `dependency.intra_table_ref` |
| **`ref()` across projects** | Cross-table dependency | Built — `cross_table_parameter`; this is the core value |
| **`source()`** | The documents under review | **Gap** — sources aren't modeled at all |
| **Source freshness** | New/amended docs in the data room since last run | **Gap** — see §4.2 |
| **Seeds** | Firm standard, controlled fallback vocabulary | Built — `standard` |
| **Vars / macros** | Shared parameters | Built — `shared_parameter`, `parameter_binding` |
| **Snapshots** | Prompt version history | Built — `prompt_version`; `run` snapshots executed versions |
| **Generic data tests** | Deterministic lint applied to every prompt | Built — `prompt_check` §8 |
| **Singular data tests** | Per-column expected behavior on a test doc | Built — `eval_result` |
| **Unit tests (fixtures)** | Test document set with known expected answers | Built — the skill's `evaluation.md` set |
| **Model contract** | Native type + configured options + fallback set, enforced pre-store | Built — `prompt_check` pre-ingest is exactly contract-at-build-time |
| **Model versions (coexisting v1/v2)** | — | Skip — see §5 |
| **Exposures** | The diligence memo | **Partial** — `coverage_check` runs forward, not backward. See §4.1 |
| **Lineage graph / docs site** | `matter_overview`, `columns_find` | Partial — queryable, not viewable. See §4.4 |
| **`state:modified` / `--select +model+`** | `impact_of_change`, `staleness_report` | Built — your strongest area |
| **Artifacts (`manifest.json`)** | — | **Gap** — see §4.3 |
| **Packages / dbt hub** | Reusable table templates per deal type | **Gap** — see §4.5 |
| **Model access, groups** | Firm baseline vs matter overlay | Built — `standard.scope` |
| **Environments (dev/prod)** | `column.status` draft → testing → verified | Built |
| **Slim CI / build gate** | — | **Gap** — see §4.6 |
| **Descriptions / doc blocks** | `column.purpose` | Built |
| **Materializations, incremental, semantic layer** | — | N/A — no execution layer |

You've independently reinvented most of dbt's core. The gaps cluster in the parts of dbt that face *outward* — toward sources upstream and consumers downstream.

---

## 4. Worth stealing

Ranked by value per unit of build effort.

### 4.1 Exposures, run backward

dbt exposures declare that a dashboard depends on a model, so that when the model breaks you immediately know which dashboard is wrong. The declaration is cheap; the reverse query is the payoff.

You have the declaration — `memo_outline`, `memo_assertion`, `assertion_source`. But `coverage_check` only traverses one direction: *does the memo have sources?* The dbt question is the other one: **this column just went stale or failed — which memo assertions are now unsupported?**

That's the question an attorney actually has at 6pm. It needs no new data, just a reverse traversal over `assertion_source`. Fold it into `impact_of_change` so a change report ends with memo consequences rather than stopping at columns.

Highest value in this document. Nearly free.

### 4.2 Source freshness

This is the gap I'd worry about most, because it is invisible.

dbt checks whether upstream tables have new data before trusting anything built on them. Your equivalent: documents get added to the data room mid-diligence, constantly. A column can be verified, unstale, and passing every eval, and still be wrong — because it was run against a 400-document set and there are now 460.

Nothing in the current model represents documents at all. `run` records which prompt versions executed but not what they executed *against*. Minimum viable fix: a document-set fingerprint on `run` (count plus a hash or a high-water timestamp), and a freshness finding when the current set has moved past the set a column was last run on.

Without this, "not stale" quietly means "the prompt hasn't changed," which an attorney will reasonably hear as "this answer is current."

### 4.3 Manifest export

dbt writes `manifest.json` every run — the full graph, versions, and test results as a portable artifact. Useful in analytics. **More** useful for you, for a reason dbt doesn't have: defensibility.

An export of the graph, prompt versions executed, eval results, and coverage state at a point in time is a record of how the diligence was conducted. That's valuable at closing, on handoff to another team, and in any later dispute about what was reviewed. Legal work has an audit demand analytics doesn't.

One tool, mostly serialization over tables you already have.

### 4.4 A lineage view

dbt's docs site is largely a lineage graph people click through, and it does more for adoption than the feature list suggests — because a DAG is the one thing genuinely easier to see than to read.

For non-technical users this may be the difference between a tool they tolerate and one they trust. Doesn't belong in the server, though: have the server return graph structure and let Claude render it as a visual in chat. No new storage.

### 4.5 Packages

dbt packages let you install someone else's models instead of rewriting them. Your version: a verified table for a deal type — data room index, corporate entity table, material contracts — promoted out of a finished matter into a firm-level template that seeds the next one.

This is the feature with the biggest firm-wide payoff and the largest build cost, since it needs template storage, parameterization, and versioning of the templates themselves. Deliberately post-P3. But the schema decision that keeps the door open is worth making now: don't hard-bind `review_table` and `column` to `matter_id` in ways that make promotion to firm scope painful later.

### 4.6 A build gate

Slim CI is dbt's rule that nothing reaches production untested. Yours would compose checks you already have — `prompt_check`, `graph_check`, unresolved parameters, unticked coverage dimensions, open failures — into one call answering: *is this table ready to run against the real data room?*

No new logic, just composition. And it's the kind of tool a paralegal can be told to run without understanding what's underneath, which fits your consolidation problem: this is one attorney-legible verb standing in front of four technical ones.

---

## 5. Deliberately don't steal

**Model versions (coexisting v1 and v2).** dbt supports this because different consumers migrate at different speeds. Your consumer is one memo. Version history yes, concurrent live versions no.

**Materializations, incremental models.** Execution concepts. Harvey's.

**Semantic layer / metrics.** Solves consistent metric definitions across BI tools. You have one deliverable.

**dbt's severity levels (`warn` vs `error`).** Tempting, and it violates findings-not-verdicts. Severity is a legal judgment about a specific matter — an inconsistent date format is trivial in one table and serious in another. Report the finding; let Claude and the attorney weigh it.

---

## 6. Crib sheet

| dbt | prompt-graph |
|---|---|
| model | column prompt |
| project | matter |
| `ref()` | `@Column` / dependency |
| source | data room document set |
| exposure | memo assertion |
| test | eval |
| manifest | matter export |
| package | deal-type table template |

---

## 7. If you act on one thing

**§4.2, source freshness.** The others make the tool better. That one closes a hole where the system can confidently report a stale answer as current — and in diligence, a confidently wrong answer costs more than a missing one.
