# prompt-graph — hosting the read layer on Azure

**Extends:** `prompt-graph-mcp-requirements.md`, `prompt-graph-addendum-a.md`
**Date:** 2026-09-15
**Status:** proposal. Nothing here is built. No Azure resource has been provisioned, no Dockerfile
exists, and the measurements in D.1 were taken read-only against the live database.

**Subscription:** personal, not a client tenant. That is a decision, not a default, and D.6
depends on it.

Covers what it would take to put the FastAPI read layer and the Next.js UI on the public
internet. It does not cover hosting the MCP server, which D.2 argues against for now.

---

## D.0 Why this is harder than "put the API on a server"

The MCP server and the read API are co-located by design, and the co-location is load-bearing.

```
Claude Code ──stdio──> MCP server ──writes──┐
                                            ├── one SQLite file, WAL
UI ──HTTP──> FastAPI read API ──mode=ro─────┘
```

The API holds one long-lived reader whose `PRAGMA data_version` counter detects commits made by
the MCP process. That is the entire mechanism behind the two-window model: say something in
Claude, the MCP writes, the watcher ticks, the UI updates. It works because both processes have
the same file on the same filesystem.

Hosting separates them across a network. **How you separate them determines every other
decision**, including whether SQLite survives at all. So the question is not which Azure service
to pick. It is which of the three shapes in D.2 you are building.

---

## D.1 What is actually in the database

Measured 2026-09-15 against `~/.prompt-graph/prompt-graph.db` opened `mode=ro`. Re-measure before
relying on any of this, because a single real Harvey run invalidates the whole section.

| | |
| --- | --- |
| Runs | **0** |
| Eval results | **0** |
| Run snapshots | **0** |
| Document set snapshots | **0** |
| `Target Legal Name` | unresolved, value NULL |
| Table instructions still holding the literal `[TARGET ...]` placeholder | 13 of 13 |
| Matter names | "Diligence Corpus Library", "M&A Review Table Suite" |
| Prompt versions / total prompt text | 973 / 1,594,884 chars |
| Requirements, and their single source | 25, all from "Harvey Prompt Playbook: Corporate M&A" |
| Database file | 3.1 MB |

**There are no deal facts in this database.** No target entity, no documents, no answers, no
vault contents, no client name in either matter title. Nothing has been run against a real data
room, which is exactly what the 0/0/0 row says.

What is in there is 1.6 MB of prompt text and the structure around it.

**Consequence, and it is the one that sets the security bar.** The exposure risk is *work
product*, not client confidence. No privilege concern, no data-residency question, no
notification obligation, no client consent to obtain. The requirement is narrower and cheaper:
**it must not be publicly reachable or crawlable.** Platform-level auth satisfies that
completely, and D.3 uses it because it is free, not because the data demands it.

This is a measured claim with an expiry date. The first real run puts extracted document content
into `eval_result` and file names into `document_set_snapshot`, and at that moment this section
is false and the bar moves.

---

## D.2 Three shapes

| | What moves to Azure | Liveness | Effort |
| --- | --- | --- | --- |
| **A. Published snapshot** | API + UI, reading an uploaded copy | none, as-of a moment | ~1 day |
| **B. Everything remote** | MCP (over HTTP) + API + UI, one shared DB | full | weeks |
| **C. Replicated reader** | API + UI, reading a replicated DB; MCP stays local | seconds of lag | ~3 days |

**Shape B is the real product and is not the next step.** It needs two things that do not exist:
an authentication story for the MCP server (today it is stdio only, and stdio has no remote
analogue), and storage that SQLite can safely write to on Azure (D.4). Either alone is a project.

**Shape C is the clever option.** Replicate the SQLite file to Blob Storage, serve reads from a
replica, keep the MCP stdio and local so no MCP auth work is needed. Hold it in reserve.

**Shape A is the recommendation**, on a reason worth stating plainly:

> The live two-window loop is an operator feature, not an audience feature. You need to watch it
> update because you are driving. Attorneys need to look at it. Hosting is for them, so hosting
> does not need liveness.

That single observation removes the MCP auth problem and the SQLite-writes problem in one move,
and it costs only the thing nobody in the audience was going to use.

---

## D.3 Shape A, concretely

Two Container Apps in one environment:

| App | Ingress | Notes |
| --- | --- | --- |
| `pg-api` | **internal only** | FastAPI. Not reachable from the internet at all. |
| `pg-ui` | external | Next.js. Managed TLS, free FQDN. |

**Single origin comes free.** A Next.js `rewrites()` entry proxies `/api/*` to the internal API
URL. No Front Door, no CORS configuration, and `allowed_origins()` in `api.py` stops mattering
because the browser only ever talks to the UI's origin. The comment already in that file ("Hosting
will put both behind one origin") is satisfied by the rewrite rather than by a gateway.

**One environment variable does the wiring.** `ui/lib/api.ts` reads
`process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8787"`, and every route is already shaped
`/api/...`. Setting `NEXT_PUBLIC_API=""` at build time makes every call a same-origin
`/api/matters` that the rewrite catches. Nothing else in the UI changes.

**Auth: Easy Auth with Entra on `pg-ui`.** Platform level, no application code, free. D.1 says the
bar is "not public", and this clears it.

**The database ships as a blob.** Storage account holds the snapshot; the API container downloads
it to local ephemeral disk on startup and opens it read-only.

This last choice is why shape A is cheap rather than merely smaller. **It sidesteps the SQLite
storage problem entirely:** WAL locking over SMB only bites when something writes, and here
nothing does. Checkpoint before uploading so the snapshot is one self-contained file:

```
PRAGMA wal_checkpoint(TRUNCATE);
```

then copy, upload, and read from the container's own local disk. No Azure Files, no shared-memory
locking, no corruption mode.

**Do not bake the database into the image.** Lower sensitivity does not make that good hygiene,
it puts work product in a container registry, and it means every data refresh becomes an image
rebuild.

---

## D.4 What shape A does not solve

Stated here so that shipping it is not mistaken for having finished.

**SQLite on Azure persistent storage remains unanswered.** App Service and Container Apps persist
through Azure Files, which is SMB, and WAL requires shared-memory locking that SMB does not
provide correctly. The failure is `SQLITE_IOERR` or silent corruption, not a clean error. Shape A
avoids this by having no writer. Shapes B and C do not get to avoid it, and must choose among a
VM with a managed disk, file-level replication, or a migration to Postgres.

**Single tenancy remains unanswered.** One database file, matters as rows, no user model, no
row-level isolation. Correct for one operator. Wrong the moment a second person has a login and
should not see every matter. Easy Auth authenticates; it does not authorize per-matter.

**Snapshot staleness is a new problem A creates.** A stale governance tool is worse than no
governance tool, because it still looks authoritative. Every page needs a visible "as of"
timestamp. It is roughly an hour of work and it is the easiest item in D.5 to skip.

---

## D.5 Work items

1. Dockerfile for the API (uv project).
2. Dockerfile for the UI. Requires `output: "standalone"` in `next.config.ts`.
3. `rewrites()` entry plus the `NEXT_PUBLIC_API=""` build arg.
4. A `publish` script: checkpoint WAL, copy, upload to blob.
5. The "as of" stamp, from D.4.
6. `az containerapp up` twice, then enable Easy Auth on `pg-ui`.

Nothing here is on the critical path for the 2026-09-16 test, and starting it beforehand trades a
working local demo for a half-deployed one.

---

## D.6 Cost

Container Apps consumption includes a monthly free grant (180,000 vCPU-seconds, 360,000
GiB-seconds, 2,000,000 requests). Two scale-to-zero containers serving an occasional demo sit
inside it. A 3.1 MB blob is immaterial.

Realistic range: **$0 to $5 per month.**

Three things would break that, all avoidable: Azure Front Door (roughly $35/mo, and D.3 makes it
unnecessary), an always-on App Service plan, and the Container Apps dedicated tier.

---

## D.7 Open questions

1. **Third-party IP.** The register reproduces the structure of a vendor document: 25
   requirements, all sourced to "Harvey Prompt Playbook: Corporate M&A". Behind a login on a
   personal subscription this is unremarkable. It deserves a deliberate answer before anything
   wider, and it is a second, independent reason to keep authentication on regardless of what
   D.1 says about sensitivity.
2. **When does D.1 expire.** The security bar here rests on the database holding no deal facts.
   That should be re-measured, not assumed, on the first run that records real results, and this
   document should be revised rather than quietly relied upon.
3. **Does A ever become C.** If the answer is yes, the Dockerfiles and the single-origin rewrite
   carry over unchanged and only the storage layer is new. If the answer is no, A is the
   permanent shape and the "as of" stamp matters more than anything else in D.5.
