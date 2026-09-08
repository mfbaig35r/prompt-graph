# Your review tables are a data pipeline. Start treating them like one.

I want to talk about a problem that I think most people running AI document review have and almost nobody has named.

Here is the setup. You are running M&A diligence in Harvey. One matter is roughly twelve review tables. Each table has about thirty columns. Each column is a prompt. That is 360 prompts, written by hand, revised by hand, and serving exactly one deliverable: the diligence memo.

Now ask yourself three questions.

1. When someone edited the prompt in column 14 of the charter table last Tuesday, what changed?
2. The entity table resolves the target's exact legal name. Six other tables use that name in their Table Instructions. If the entity table changes, which of the other eleven tables are now wrong?
3. Every column passed its test. Can you write the change-of-control section of the memo?

If you can answer all three from memory, you have a very small matter or a very good memory. For everyone else, the honest answers are "I'd have to diff it against a copy I hopefully saved," "I'd have to think about it," and "I have no idea until I try."

I have been here before. Not in legal, but the shape is identical. Around 2016 the analytics world had exactly this problem with SQL. Hundreds of queries, written by hand, each one correct in isolation, no idea what depended on what, no idea whether the dashboard at the end could actually be built from them. The fix was not a better SQL editor. The fix was to admit that the queries were software and give them the things software has: version control, a dependency graph, tests, and a definition of "done" that comes from the consumer, not the producer.

That is what `prompt-graph` is. It is a small MCP server that sits behind Claude and treats your review tables like the pipeline they are. This post walks through using it on one matter, start to finish. The matter is fictional (Project Harbor, four tables), but the workflow is the one I would use on a real one.

## The division of labor, because it matters

Before the walkthrough, one design principle, because if you get this wrong the whole thing becomes unusable for the people it is for.

The users are attorneys and paralegals. They work in a chat window. They will never see a tool name, an id, a JSON blob, or a stack trace. Everything below happens by the user saying something in English and Claude deciding what to call.

So there are three layers, and each one owns something specific:

| Layer | Owns |
| --- | --- |
| The `legal-review-table-builder` skill | Judgment. What a column should ask, how to scope it, which fallback state applies, how to diagnose a bad output. |
| Claude | Reading messy input, deciding what to call, interpreting results, explaining consequences. |
| `prompt-graph` | State and arithmetic. Storage, versions, the dependency graph, staleness, deterministic lint, coverage math. |

The server never writes a prompt. It never reads a file. It never makes a legal determination. It returns *findings*: one factual sentence with a stable code and a subject. "The prompt presents `N/A` as a returnable value." Not "this is a critical vocabulary violation, rewrite it as follows." Claude turns the finding into advice in the skill's voice. Keeping the judgment out of the server means server output never has to be re-litigated when firm practice changes, and it means an attorney is never reading a hardcoded string that sounds like legal advice.

If you are coming from the analytics engineering world: the server is the DAG, the tests, and the freshness checks. It is not the analyst.

## Step 1: Open the matter

You say: *"Open Project Harbor."*

Claude calls `matter_open`. What comes back is the state of the whole suite: every table, column counts by status, which tables have been run, how many columns are stale, which shared parameters are unresolved, whether a memo outline exists. Claude summarizes it in two sentences. On a matter that has been running for three weeks, this is the part I find most valuable, because it is the part nobody ever writes down.

Two small things here that I care about more than they might seem to deserve.

First, if you say a name that does not exist, the server does not create it. It lists the matters that do exist and asks. A typo creating a phantom matter in a client-confidential data store is the kind of small failure that erodes trust fast, and it is cheap to prevent.

Second, if you just say *"what matters do we have?"* you get the list. The model should not have to guess a wrong name on purpose to discover what is there.

## Step 2: Get the prompts in

This is where most tools of this kind get the boundary wrong, so let me be precise about it.

You have an Excel export from Harvey, or a CSV, or you paste thirty prompts into the chat. **Claude reads it.** Claude extracts one record per column: name, position, native type, the prompt text, the configured options if it is a Classify column. Then Claude calls `table_ingest` with those records.

The server does not parse Excel. It never will. Parsing messy human artifacts is exactly what the model is good at and exactly what a deterministic server is bad at. If the server had a file parser, every weird export format would become a server bug. Instead it has one stable input contract, and the messiness lives with the thing that can handle messiness.

You say: *"Here's the entity register export. The Table Instructions are the block I pasted above it."*

Claude ingests the table and its Table Instructions together. That second part matters: Harvey exports omit Table Instructions, so if you do not store them somewhere, the only copy is in the Harvey UI. The server is the authoritative copy from this point on.

Every column gets version v1.0. Every `@Column` reference in every prompt is resolved against the table's other columns. If one does not resolve, you hear about it. And every stored prompt is linted (more on that in step 4).

Now the part I actually want to emphasize: **ingest is idempotent.** Re-ingest the same export next week and nothing happens. Re-ingest an export where two prompts changed and those two columns get v1.1 with a change note saying where it came from; the other twenty-eight are untouched. A column that has disappeared from the export is reported, not deleted. Nobody has to think about whether it is safe to re-import. It is always safe.

This is the same property that makes `dbt run` safe to run twice. It sounds like a small thing. It is the thing that lets people stop being afraid of the tool.

## Step 3: Declare what crosses tables

Here is the actual reason this server exists.

Harvey's `@Column` reference works *within a table*. A column in the charter table can reference another column in the charter table. It cannot reference the entity table. But the dependency is real: the entity table resolves "Harbor Logistics Holdings, LLC" as the exact legal name of the target, and that string then appears in the Table Instructions of six other tables. When the entity table's prompt changes, those six tables are now built on a value that may have moved. Harvey has no idea. Nothing tells anyone.

In dbt terms, you have a model that six other models depend on, and no `ref()`.

So you declare it. You say: *"The target's legal name is Harbor Logistics Holdings, LLC. It comes from the Principal Entity column of the entity register. The charter, lease, and contracts tables all use it in their Table Instructions."*

Claude calls `parameter_set`. The server records the value, its source column, and each consumer, and materializes edges in the dependency graph from the source column to every column in every consuming table. Now the cross-table dependency exists somewhere. It is the only place it exists, which is a discipline the team has to keep, but it is a discipline that pays for itself the first time the entity table changes.

The server also checks the obvious thing: does the Table Instructions text of each consuming table actually *contain* the value? On the demo matter, the lease table's instructions print the subsidiary as "Harbor Cold Chain LLC" and the standard says "Harbor Cold Chain, LLC". That comma is the difference between a column that returns the exact name and a column that returns a variant, and the server finds it in about four milliseconds.

## Step 4: Check the suite before you run it

You say: *"Is anything wrong with the suite?"*

Claude calls `suite_check`. This is the equivalent of `dbt test`, and it covers four families of things I used to catch by rereading 360 prompts and hoping.

**Prompt lint.** Every rule from the skill's "final prompt check," made deterministic. Character count against Harvey's limits. The controlled fallback vocabulary: exactly five states, no synonyms, so `N/A` or `Unclear` in a prompt gets flagged. `Not stated` used outside a Date, Number, Currency, or Duration column. A Classify prompt that names a label not in its configured options. A prompt with no output contract. A rule that asks the model to count characters, which models do badly. A column declared as an input in the preamble that no rule then uses.

**Graph.** Dependency cycles. A reference to a column positioned later in the table. A narrative Free Response column feeding three downstream columns, which the skill warns against because any wording change upstream then alters every dependent result.

**Parameters.** A parameter nobody consumes. A parameter that is consumed but never resolved. A consuming table that never binds the value into its Table Instructions.

**Consistency.** Date patterns that differ from the firm standard. Two currency styles in one matter. An entity printed three different ways. The same concept ("change of control consent") extracted under three different column names across three tables, with three different option sets.

That last one is the finding I would have paid for. On the demo matter it is there by design, and it is exactly the kind of thing that is invisible when you look at one table at a time and obvious when something can see all twelve.

Every one of these comes back as a finding. Claude groups them by table, leads with what changes your next action, and explains each one in the skill's voice. You never see a code.

## Step 5: Revise, and store the revision

Your test run shows the Execution Status column returned `Unsigned` on a conformed closing set, because `/s/` signatures were not in its definition of a signature marker. The skill diagnoses it (evidence overstatement), drafts the fix, and you approve it.

You say: *"Store that as the new version. It fixes the conformed signature problem."*

Claude first runs `prompt_check` on the draft, because storing a prompt you already know will be flagged is silly. Then `column_revise`: new version v1.1, change note, failure class addressed. The change log now reads exactly like the skill's inventory template, except nobody typed it into a Markdown table.

One rule I want to call out: **a rename is explicit.** If you re-ingest an export where "Doc Type" became "Document Type", the server treats that as a new column and reports that the old one is missing. It does not guess. If you want a rename, you say so, and then the server tells you which other prompts still reference `@Doc Type` so you can fix them. It does not fix them for you. It never edits prompt text.

## Step 6: Plan the rerun from the graph, not from memory

This is the step the whole thing is built around.

You say: *"I changed Execution Status. What do I need to rerun?"*

Claude calls `impact_of_change`. Back comes every column downstream of Execution Status, across every table, in dependency order. Each one is marked *direct* (it references Execution Status itself) or *transitive* (it references something that does). Each one says which kind of dependency carries it: a real Harvey `@Column`, a shared parameter, or an advisory dependency the team declared because Harvey cannot express it.

That last distinction matters for the rerun. Harvey will sequence the `@Column` dependents correctly if you rerun them. It will do nothing about the parameter-mediated ones, because it does not know they exist. So the plan says, in effect: rerun these two columns in the entity table, and then these four columns in the charter table are stale by convention, and here is the order.

And then you say: *"What's stale right now, across everything?"*

`staleness_report` compares every column's current prompt version against the version that was actually executed in its last run. Direct staleness: the prompt, its table's instructions, or a bound parameter changed after the last run. Transitive: something upstream changed. Never run: no run recorded at all. It hands back a dependency-ordered rerun sequence for the stale set.

This is freshness for prompts. It is not a new idea. It is just an idea nobody had applied here.

## Step 7: Record what happened

After you run the table in Harvey, you say: *"We ran the entity register today against the fourteen-document test set. Here are the results."*

`run_record` snapshots which prompt version each column was on, so staleness has something to compare against next time. You also tick which test-set dimensions the corpus covered: signed and unsigned documents, silent documents, documents that incorporate external terms, and so on. The skill's evaluation log has fourteen of these. **Tick only the ones you actually tested.** An unticked dimension is treated as open risk, and that treatment propagates all the way to the memo coverage report.

Then `eval_record` takes the results in one batch, passes as well as failures, in the same shape as the skill's evaluation log CSV. A bad failure class in one row does not reject the batch; it stores the row and reports the problem with the accepted values. Nobody loses forty rows of work because one cell was spelled wrong.

Two runs later, you say: *"Did v1.2 fix the notary problem without breaking anything?"* and `run_compare` tells you: fixed, still failing, newly failing. That third bucket is regression detection. Harvey does not have it. Now you do.

## Step 8: Ask the only question that matters

Everything above is about whether the columns are *correct*. This step is about whether they are *sufficient*, and I want to be clear that these are different questions. Every column can pass and the memo can still be undraftable.

The move is to invert the analysis. Start at the memo.

You say: *"Here's the memo outline. Under Change of Control we need to be able to state charter-level consents, transfer restrictions, leases needing landlord consent, and contracts with change-of-control triggers. And we need to say whether the deal actually trips each one, but that's the deal team's call, not the table's."*

Claude calls `memo_outline_set` with each assertion marked one of two ways. **Extraction:** document evidence a column can supply, mapped to the columns that supply it. **Judgment:** a determination the attorney makes. Which document is operative. Whether consent is required or properly obtained. Materiality. Deal consequence.

Then `coverage_check`. For every assertion, one of four answers:

- **Reliably covered.** At least one source column has a run, no open failure, is not stale, and its table ticked every applicable test dimension.
- **Nominally covered.** Sourced, but every source has an open failure, an unticked dimension, no run, or is stale. The finding names each source and why.
- **Extraction gap.** No column supplies this. This is a schema defect. Add a column.
- **Judgment boundary.** The attorney supplies this. This is *correct*. Do not add a column.

I cannot stress the last distinction enough, because collapsing it is how you end up with a column that asks Harvey whether a transaction is enforceable. The two kinds of gap look identical in a spreadsheet. They are opposites in practice. One is a bug in the table design. The other is the table design working as intended, and the report exists partly so that nobody later "fixes" it.

The report also lists every column that feeds no assertion at all. On the demo matter that is eight of eighteen. Either the outline is incomplete or those columns do not need to exist, and either way it is worth knowing before you run 360 prompts across a data room.

If you have used dbt exposures, this is that, with the sufficiency test the exposures feature never quite got around to.

## What this does not do

I want to be honest about the edges, because a tool that overclaims in legal is worse than no tool.

It barely talks to Harvey. Prompts go in by export or paste, and results come back the same way. The one thing it will ask Harvey directly, if you give it an API key, is how many documents are in the vault, so it can tell you that a table last ran against 400 documents and there are now 447. Without a key you tell it the count yourself and it says so in the finding. Harvey's API cannot read column definitions, so that is not a shortcut around ingest.

It does not stop someone editing a prompt in the Harvey UI and forgetting to tell it. The inventory is authoritative by policy, and the reconciliation path is to re-ingest the export, which is safe and will show you what moved. But it is a policy, not a lock.

It does not do access control. The database is one SQLite file. Treat it like a matter file: put it on a volume the firm controls, restrict who can read the directory, back it up with everything else.

And it does not have opinions. Every finding is an observation. If your firm decides next year that `Unclear` is an acceptable fallback state, you change one list and every check follows. Nothing in the server argues with you.

## The actual point

Here is what I think is going on underneath all of this.

The interesting work in AI document review is not prompt writing. Prompt writing is table stakes, and the skill handles it well. The interesting work is *maintenance*: knowing what you have, knowing what depends on what, knowing what is stale, knowing whether the thing you built can actually produce the thing you owe the client. That work has no natural home in a chat window, because a chat window has no state and cannot see twelve tables at once.

Giving it a home is not glamorous. It is a dependency graph and a version table and a handful of deterministic checks. But it is the difference between a suite of prompts that one person understands and a suite of prompts that a team can maintain for the life of a matter.

We learned this once already with SQL. It would be a shame to learn it again from scratch.

---

*prompt-graph is an MCP server for Claude. It runs locally over stdio against a single SQLite file, and it ships with a fictional four-table matter you can open in about a minute. The companion skill, `legal-review-table-builder`, does the drafting and the diagnosis; the server does the remembering.*
