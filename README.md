# prompt-graph

An MCP server that stores, versions, validates, and computes over the Harvey review-table
prompts of an M&A diligence matter. It is the state-and-determinism companion to the
`legal-review-table-builder` skill: the skill drafts and revises prompts, Claude reads
exports and interprets results, and this server holds the inventory, the cross-table
dependency graph, staleness, document-set freshness, evaluation history, and memo coverage.

The server never drafts prompt text, never parses files, and never makes a legal
determination. Every tool returns findings (factual observations with a stable code) for
Claude to interpret in the skill's voice.

## What you need

- Python 3.11 or newer (`python3 --version`)
- Either [`uv`](https://docs.astral.sh/uv/) or `pip`
- Claude Desktop, Claude Code, or any MCP client that speaks stdio

## Install

From this directory:

```bash
# with uv (recommended)
uv venv .venv
uv pip install --python .venv/bin/python .

# or with pip
python3 -m venv .venv
.venv/bin/pip install .
```

This installs a `prompt-graph` executable inside `.venv/bin/`. Check it:

```bash
.venv/bin/prompt-graph --migrate
# schema version 3 at /Users/<you>/.prompt-graph/prompt-graph.db
```

## Configure

The server keeps one SQLite database file. By default it lives at
`~/.prompt-graph/prompt-graph.db`. Set `PROMPT_GRAPH_DB` to put it somewhere else, for
example on an encrypted volume the firm controls.

The database holds client-confidential material (prompts, Table Instructions, entity
names, matter objectives). Treat the file like a matter file: restrict who can read the
directory, back it up with the firm's normal process, and keep the `-wal` and `-shm`
sidecar files with it (they are part of the database while the server is running).

`matter_export` writes its JSON records to an `exports` folder beside the database unless
told otherwise; those files are client data too.

### Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "prompt-graph": {
      "command": "/absolute/path/to/prompt-graph/.venv/bin/prompt-graph",
      "env": {
        "PROMPT_GRAPH_DB": "/absolute/path/to/matters/prompt-graph.db"
      }
    }
  }
}
```

Restart Claude Desktop. The server appears as "prompt-graph" with 24 tools.

### Claude Code

```bash
claude mcp add prompt-graph \
  -e PROMPT_GRAPH_DB=/absolute/path/to/matters/prompt-graph.db \
  -- /absolute/path/to/prompt-graph/.venv/bin/prompt-graph
```

### Try it with the demo matter

The repository ships a fictional four-table matter (Project Harbor, the skill's worked
example extended) so the graph, staleness, evaluation, and coverage tools can be shown
without client data:

```bash
.venv/bin/prompt-graph --db /tmp/harbor-demo.db --seed-demo
```

Point the MCP config at `/tmp/harbor-demo.db` and ask Claude to open Project Harbor.

### Harvey Vault API (optional)

Document-set freshness can poll the Harvey Vault API instead of relying on a manually
supplied document count. Set `HARVEY_API_KEY` (a bearer token, server-side only) and, for
EU or AU deployments, `HARVEY_API_BASE` (`https://eu.api.harvey.ai` or
`https://au.api.harvey.ai`). Vault endpoints allow ten requests a minute per organisation;
the server caches an observation for five minutes, never polls per column, and spends at
most eight requests per call across every project it observes. A vault too large to
enumerate within that budget is reported (`DOCSET_TOO_LARGE_TO_ENUMERATE`) and no snapshot
is written, because a prefix of the file list is not the document set. Without a
key, `freshness_check` accepts a manual count and says so in its findings.

## The read-only UI (optional)

A Next.js view of the same database, for watching a session's work at scale beside the Claude
window. It is read-only by construction: the API process opens SQLite with `mode=ro`, never
migrates, and SQLite refuses writes on that connection. The MCP server stays the only writer.

```bash
uv pip install --python .venv/bin/python -e ".[ui]"
.venv/bin/prompt-graph-api                 # read API on 127.0.0.1:8787
cd ui && pnpm install && pnpm dev           # UI on localhost:3000
```

Open `http://localhost:3000`, not `127.0.0.1:3000`: Next treats them as different origins and
blocks its own dev resources from the second, which stops the page hydrating.

The UI polls `/api/version` once a second. That returns `PRAGMA data_version`, which changes
when another connection commits, so a table ingested through Claude appears without a reload.
Point `prompt-graph-api --db` at the demo matter to see the evaluation views carry data; the
prompt library has no recorded runs, so staleness and failures read as empty there.

### Showing it on another machine

The database is a local file and this view reads it directly, so "sharing the UI" is really a
question about where that file goes. Decide which database first.

- **Project Harbor** (`prompt-graph --db /tmp/harbor.db --seed-demo`) is fictional and safe to
  copy anywhere. It is also the only database with recorded runs, so the evaluation views carry
  data there and read as empty against a prompt library that has never been run.
- The **prompt library** is derived, not source: the markdown in `diligence-kernel` is the
  source of truth and `scripts/rebuild_corpus.sh` reconstructs the database from it. Rebuild it
  rather than copying a `.db` around.
- A **real matter** is client data. Copying it to another machine is a data-handling decision,
  not a setup step.

```bash
scripts/rebuild_corpus.sh                    # into $PROMPT_GRAPH_DB or the default path
scripts/rebuild_corpus.sh --db /tmp/demo.db  # into a throwaway file
scripts/rebuild_corpus.sh --dry-run          # parse and report, write nothing
```

It finds `diligence-kernel` as a sibling checkout, at `$DILIGENCE_KERNEL`, or clones it into
`~/.cache/prompt-graph/`, creates the matter if it is absent, and replays the markdown through
`table_ingest`. Re-running is safe: versioning is by content, so unchanged prompts are left
alone and only genuinely changed ones get a new minor version. It runs in this repo's venv;
the kernel's heavier extras are not imported on this path.

**Run it on the other machine.** The portable option: everything stays local to whoever is
looking at it.

```bash
git clone git@github.com:mfbaig35r/prompt-graph.git && cd prompt-graph
uv venv .venv && uv pip install --python .venv/bin/python -e ".[ui]"
.venv/bin/prompt-graph --db ~/.prompt-graph/prompt-graph.db --seed-demo   # or copy a .db across
.venv/bin/prompt-graph-api &
cd ui && pnpm install && pnpm dev
```

Copy the `-wal` and `-shm` sidecars with the `.db` if the server was running when you copied it,
or checkpoint first with `sqlite3 the.db "PRAGMA wal_checkpoint(TRUNCATE);"`.

**Serve it to another machine on the same network.** Both processes have to bind beyond
loopback, and the browser's origin changes, so the API has to be told to accept it:

```bash
PROMPT_GRAPH_UI_ORIGINS="http://192.168.0.129:3000"   .venv/bin/prompt-graph-api --host 0.0.0.0 &
cd ui && NEXT_PUBLIC_API=http://192.168.0.129:8787 pnpm dev -H 0.0.0.0
```

Use the machine's real address in all three places. Miss the origin and the page sits on
"Loading" with nothing in the API log, because the browser blocks the call before it is sent.

**Over the internet.** A tunnel needs both ports exposed, `NEXT_PUBLIC_API` pointed at the
tunnelled API, and that URL in `PROMPT_GRAPH_UI_ORIGINS`. There is no authentication in front of
any of this: anyone with the link reads the whole matter. Fine for Harbor, not for client data.
For a client demo, screen sharing carries none of that risk.

## Upgrades

Schema migrations are applied automatically when the server starts, and recorded in the
`schema_version` table. To upgrade, install the new version over the old one and restart
the client. Back up the database file first.

## The tools

All tools take matters, tables, columns, and parameters by name. A user never sees these
names; Claude calls them from natural-language requests.

| Tool | What the user asks |
| --- | --- |
| `matter_open` | "Open Project Harbor" / "Where are we on Harbor?" / "What matters do we have?" |
| `standard_set` | "Set the firm baseline" / "The review subjects for this matter are…" |
| `table_ingest` | "Here is the entity table" (Claude extracts records from the export) |
| `table_instructions_set` | "Update the Table Instructions on the contracts table" |
| `column_revise` | "Store this as v1.1 of Execution Status" / "Rename…" / "Retire…" |
| `column_read` | "Show me the Signatories prompt and its history" |
| `columns_find` | "Which Classify columns are still in draft?" |
| `requirements_ingest` | "Here is the playbook this suite is built to satisfy" |
| `requirement_set` | "3.4.7 Part A needs the buyer's checklist; Part B becomes section IV.B" |
| `concept_set` | "These are all the same concept" / "No, those two are different things" |
| `prompt_check` | "Check this draft before I store it" |
| `suite_check` | "Is anything wrong with the suite?" / "Does it support the memo?" |
| `impact_of_change` | "If the entity name column changes, what do I rerun?" |
| `staleness_report` | "What's stale since the last run?" |
| `parameter_set` | "The target's legal name is X, from the entity table, used by these tables" |
| `run_record` | "We ran the charter table today against the 14-document test set" |
| `eval_record` | "Log these results" |
| `failures_summary` | "What's failing, by class?" |
| `run_compare` | "Did v1.2 fix the notary problem without breaking anything?" |
| `memo_outline_set` | "Here is the memo outline and what each section has to say" |
| `coverage_check` | "Can the suite support the memo?" |
| `freshness_check` | "Has the data room grown since we ran the leases table?" |
| `table_readiness` | "Is the charter table ready to run against the real vault?" |
| `matter_export` | "Give me a record of everything we reviewed and when." |

Finding codes are listed in `PLAN.md`. Design choices and deviations from the
requirements are in `DECISIONS.md`.

## Development

The `legal-review-table-builder` skill is a separate repository. One test reads its worked
examples and skips when the skill is not checked out beside this repo; set
`LEGAL_REVIEW_SKILL_DIR` to point elsewhere.

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```

Tests run against an in-memory database; nothing touches `~/.prompt-graph`.

CI runs ruff, the tests on Python 3.11 and 3.12, and a stdio start-up check on every push
and pull request. The tests that pin the server's vocabularies to the skill's files skip in
CI unless the repository secret `SKILL_REPO_TOKEN` (a fine-grained personal access token
with read access to `mfbaig35r/legal-review-table-builder`) is configured, in which case
the skill is checked out beside the code and they run.

## Layout

```
src/prompt_graph/
  server.py      the 24 MCP tools (docstrings written for the model)
  db.py          SQLite connection, WAL, versioned migrations
  constants.py   vocabulary, taxonomy, coverage dimensions, copied from the skill
  lint.py        prompt_check rules
  refs.py        @Column reference parsing
  service.py     matter, standard, ingest, revise, read, find
  graph.py       dependency graph, impact, cycles, staleness
  parameters.py  shared parameters and bindings
  checks.py      suite_check
  evaluation.py  runs, results, failures, run comparison
  coverage.py    memo outline, coverage, reverse coverage (column -> assertions)
  freshness.py   document-set snapshots and source freshness
  harvey.py      minimal Vault API client (stdlib, injectable fetcher)
  readiness.py   table_readiness composition
  export.py      matter_export
  seed.py        demo matter loader
  requirements.py the requirement register: the specification a suite satisfies
  api.py         read-only HTTP API for the UI (optional [ui] extra)
ui/              Next.js read-only view (overview page)
fixtures/demo_matter.json
tests/
```
