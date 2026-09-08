# prompt-graph — Addendum A

**Extends:** `prompt-graph-mcp-requirements.md`
**Source of the ideas:** `prompt-graph-dbt-mapping.md` §4
**Date:** 2026-09

Five additions. A.1 needs the Harvey API; A.2 through A.5 need nothing new. A.1 also partially answers open question §12.3.

---

## A.1 Source freshness

### The problem

`run` records which prompt version executed. It does not record what that prompt executed *against*. Staleness therefore only ever compares prompts to prompts.

Documents arrive throughout a diligence. A column can be `verified`, unstale, and passing every eval while being wrong, because the vault has grown since it last ran. The failure is silent and it points the wrong way: the system reports confidence it hasn't earned. In diligence a confidently wrong answer costs more than a missing one, so this is the most consequential gap in the current design.

### What Harvey exposes

Verified against `developers.harvey.ai/guides/vault`, 2026-09. Vault is a real REST API, not only the MCP connector.

```
GET /api/v1/vault/projects/{project_id}/files
```

Supports cursor pagination and server-side filtering on `name`, `content_type`, `processing_status`, `uploaded_after`, `uploaded_before`, with sorting on `name`, `uploaded_at`, or `size`. Also available:

```
GET /api/v1/vault/workspace/projects   → includes files_count per project
GET /api/v1/vault/get_files?file_ids=  → per-file processing_status
GET /api/v1/vault/get_metadata/{project_id}
```

`processing_status` values include `uploaded`, `processing`, `ready_to_query`. Only `ready_to_query` files were actually available to a run — a file uploaded but still processing was not in scope, and treating it as in scope would produce false freshness alarms.

**Rate limit: 10 requests/minute on Vault endpoints.** This is low, and it shapes the design: poll on demand, cache the last observation, never loop per column. Files responses also carry `deleted_at`; a deleted document is as much a freshness event as an added one.

### Design

**Schema.** New table `document_set_snapshot`:

`id, matter_id, vault_project_id, observed_at, ready_count, latest_uploaded_at, set_hash (nullable), source ('harvey_api'|'manual')`

Add `vault_project_id` to `matter`. Add `document_set_snapshot_id` to `run`.

`set_hash` is a hash over the sorted list of `ready_to_query` file IDs. It catches deletion and replacement, which counts alone miss. Compute it when a full enumeration is affordable; fall back to `ready_count` plus `latest_uploaded_at` when it isn't.

**Tools.**

- **`document_set_refresh`** — poll Harvey for the matter's vault, write a snapshot, return what changed since the previous one. Rate-limit aware; returns the cached snapshot with its age if called again within a short window.
- **`freshness_report`** — compare the current snapshot against the snapshot recorded on each column's last run. Returns findings, in the standard finding shape.

**Findings, not verdicts.** Report the observation: *this column last ran against 412 ready documents; 47 have been added and 2 removed since.* Do not compute a severity — whether 47 new documents matter depends on what they are, which is an attorney's call.

**Manual fallback.** Where the API is unavailable, `document_set_refresh` accepts a manually supplied count and timestamp with `source='manual'`. Findings should carry the provenance, because a manual snapshot is a weaker claim than an observed one.

**Interaction with `matter_overview` and `coverage_check`.** A column running on a stale document set should not read as clean in either. Surface freshness alongside staleness rather than folding the two together — they have different causes and different remedies.

---

## A.2 Reverse coverage

`coverage_check` walks `assertion_source` in one direction: does each memo assertion have sources? The more useful question at 6pm is the reverse — **this column just failed or went stale; which memo assertions are now unsupported?**

No new schema. Traverse `assertion_source` from column to assertion.

Extend `impact_of_change` so its report ends with memo consequences instead of stopping at columns, and add the same traversal to `staleness_report` and `freshness_report`. An assertion whose only supporting column is stale, failing, or freshness-flagged should be reported as at risk with the reason attached.

This is the cheapest item here and probably the most visible to an attorney, because it translates infrastructure state into deliverable state.

---

## A.3 Matter export

dbt writes `manifest.json` on every run so downstream tooling can reason about the project. Your use is different and stronger: **a record of how the diligence was conducted.**

**`matter_export`** — serialize to a single JSON document: matter and standard in effect, tables and Table Instructions with versions, every column with its current prompt version and full version history, the dependency graph, shared parameters and bindings, all runs with their prompt-version and document-set snapshots, eval results, coverage state, and the export timestamp.

Useful at closing, on handoff to another team, on lateral departure, and in any later question about what was reviewed and when. It is also your disaster recovery story if the SQLite file is lost, and the input to A.5.

Mostly serialization over tables that already exist. Version the export format from the start — `export_format_version` — so old exports remain readable after the schema moves.

---

## A.4 Readiness check

**`table_readiness`** — one call answering: *is this table ready to run against the real vault?*

Composes checks that already exist:

- `prompt_check` findings on every column, unresolved
- `graph_check` findings scoped to this table
- unresolved shared parameters the table's Table Instructions or columns consume
- open failures from the most recent run
- unticked `coverage_dimension` entries
- columns still in `draft` status
- freshness state of the document set (A.1)

Returns findings grouped by cause, plus a plain count. No pass/fail verdict — readiness against a live client matter is a judgment, and the tool's job is to ensure nothing is missed rather than to decide.

This is also the best answer so far to the tool-surface problem flagged in §7: one attorney-legible verb standing in front of six technical ones. A paralegal can be told to run it without knowing what's underneath, which is the actual usability bar.

---

## A.5 Lineage view

The single thing genuinely easier to see than to read is a graph. For non-technical users this is plausibly the difference between a tool they tolerate and one they trust.

**Not server work.** The server returns graph structure — it already does, via `impact_of_change` and `graph_check`. Claude renders it in chat as a visual. No new storage, no new tool, no rendering code in Python.

Worth stating explicitly in the skill's `Orchestrate` mode (§13) so the behavior is consistent: when a user asks what depends on what, draw it rather than listing it.

---

## A.6 What the Harvey API findings change elsewhere

Beyond freshness, worth folding into §10 and §12 when those are revisited:

- **§12.3 is partly answered.** The MCP connector is not the only path. A documented REST API exists, so P4 is less constrained than assumed. Still inventory the connector's tool surface before building — compose where it already does the work.
- **A Review Tables API exists.** The Vault guide references endpoints for reading results from and adding rows to review tables. Not yet inventoried. If it also exposes column definitions, the manual ingest path in §5 becomes a fallback rather than the primary route, which would materially change P0.
- **Client-matter mapping and audit-log APIs exist.** Both bear on §12.2, access control and confidentiality. Harvey attributes usage to client matters; aligning prompt-graph's `matter` with Harvey's client-matter ID would let the two systems agree on scope boundaries.
- **Operational constraints to design against:** bearer token auth, server-side only; region-specific endpoints for EU and AU deployments; 10 req/min on Vault. If the firm is on a regional deployment, the base URL must be configurable rather than hardcoded.
- **§12.4 stays open.** Nothing here addresses prompts edited directly in Harvey's UI. Still the most likely real-world break, and still a policy answer more than a technical one.

---

## A.7 Build order

A.2 and A.4 are small and need nothing new — fold into P1 and P2 respectively.
A.3 slots after P3, once there is a full graph worth exporting.
A.1 needs Harvey credentials and belongs with P4, but **the schema changes should land with P0**. Adding `document_set_snapshot` and the `run` foreign key later means backfilling runs that have no document-set record, and those runs can never be made trustworthy retroactively.
A.5 is a skill change, not a server change.
