# prompt-graph

An MCP server that stores, versions, validates, and computes over the Harvey review-table
prompts of an M&A diligence matter. It is the state-and-determinism companion to the
`legal-review-table-builder` skill: the skill drafts and revises prompts, Claude reads
exports and interprets results, and this server holds the inventory, the cross-table
dependency graph, staleness, evaluation history, and memo coverage.

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
# schema version 1 at /Users/<you>/.prompt-graph/prompt-graph.db
```

## Configure

The server keeps one SQLite database file. By default it lives at
`~/.prompt-graph/prompt-graph.db`. Set `PROMPT_GRAPH_DB` to put it somewhere else, for
example on an encrypted volume the firm controls.

The database holds client-confidential material (prompts, Table Instructions, entity
names, matter objectives). Treat the file like a matter file: restrict who can read the
directory, back it up with the firm's normal process, and keep the `-wal` and `-shm`
sidecar files with it (they are part of the database while the server is running).

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

Restart Claude Desktop. The server appears as "prompt-graph" with 18 tools.

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

## Upgrades

Schema migrations are applied automatically when the server starts, and recorded in the
`schema_version` table. To upgrade, install the new version over the old one and restart
the client. Back up the database file first.

## The tools

All tools take matters, tables, columns, and parameters by name. A user never sees these
names; Claude calls them from natural-language requests.

| Tool | What the user asks |
| --- | --- |
| `matter_open` | "Open Project Harbor" / "Where are we on Harbor?" |
| `standard_set` | "Set the firm baseline" / "The review subjects for this matter are…" |
| `table_ingest` | "Here is the entity table" (Claude extracts records from the export) |
| `table_instructions_set` | "Update the Table Instructions on the contracts table" |
| `column_revise` | "Store this as v1.1 of Execution Status" / "Rename…" / "Retire…" |
| `column_read` | "Show me the Signatories prompt and its history" |
| `columns_find` | "Which Classify columns are still in draft?" |
| `prompt_check` | "Check this draft before I store it" |
| `suite_check` | "Is anything wrong with the suite?" |
| `impact_of_change` | "If the entity name column changes, what do I rerun?" |
| `staleness_report` | "What's stale since the last run?" |
| `parameter_set` | "The target's legal name is X, from the entity table, used by these tables" |
| `run_record` | "We ran the charter table today against the 14-document test set" |
| `eval_record` | "Log these results" |
| `failures_summary` | "What's failing, by class?" |
| `run_compare` | "Did v1.2 fix the notary problem without breaking anything?" |
| `memo_outline_set` | "Here is the memo outline and what each section has to say" |
| `coverage_check` | "Can the suite support the memo?" |

Finding codes are listed in `PLAN.md`. Design choices and deviations from the
requirements are in `DECISIONS.md`.

## Development

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```

Tests run against an in-memory database; nothing touches `~/.prompt-graph`.

## Layout

```
src/prompt_graph/
  server.py      the 18 MCP tools (docstrings written for the model)
  db.py          SQLite connection, WAL, versioned migrations
  constants.py   vocabulary, taxonomy, coverage dimensions, copied from the skill
  lint.py        prompt_check rules
  refs.py        @Column reference parsing
  service.py     matter, standard, ingest, revise, read, find
  graph.py       dependency graph, impact, cycles, staleness
  parameters.py  shared parameters and bindings
  checks.py      suite_check
  evaluation.py  runs, results, failures, run comparison
  coverage.py    memo outline and coverage
  seed.py        demo matter loader
fixtures/demo_matter.json
tests/
```
