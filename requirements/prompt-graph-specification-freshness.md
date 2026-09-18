# prompt-graph — specification freshness

**Extends:** `prompt-graph-addendum-a.md` (§A.1 source freshness), `prompt-graph-requirement-register.md`
**Date:** 2026-09-17
**Status:** proposal. Nothing here is built. Measurements taken against the live database
opened `mode=ro`.

The server watches the documents a review runs against and is blind to the specification the
review is measured against. This records the asymmetry and the smallest fix for it.

---

## F.0 The asymmetry

Addendum A established source freshness for the evidence side: documents get added to a vault
mid-diligence, so a column can be verified, unstale and passing while being wrong, because it
was run against a smaller set than exists now. That shipped as `freshness_check` over
`document_set_snapshot`, with `DOCSET_MOVED`, `DOCSET_UNRECORDED` and `DOCSET_UNOBSERVED`.

The same failure exists on the other side and nothing covers it.

```
        specification  ─────────────▶  correlation  ◀─────────────  documents
        (the playbook)                 (the memo)                   (the vault)
        no freshness check                                          freshness_check ✓
```

A playbook is revised between deals. When it is, every assertion correlated against the old
edition is silently measuring the suite against a superseded standard, and the Correlation page
keeps rendering `sourced` in green. The number that would tell you is not wrong. It is stale,
which is worse, because staleness is invisible and green is reassuring.

## F.1 What is recorded today

Measured 2026-09-17.

**The correlation itself is substantial.** The current outline (v5) carries 20 sections, 123
assertions and **364 source bindings**. 49 assertions carry a note and 24 of those cite the
playbook by number. This is real work: five passes through `memo_outline_set` between 00:51 and
01:43 on 2026-09-16, growing from 82 assertions to 123.

**The pointer to what it was derived from is one row of free text.**

```
name     = Harvey Prompt Playbook: Corporate M&A
citation = 103-page PDF, Section 3 (Due Diligence), in the matter folder
version  = (empty)
note     = Correlation worked out column by column against the suite.
```

`citation` is prose written for a human. `version` is empty. There is no filename, no hash, no
edition, no date of the document itself. "In the matter folder" is an instruction to a person,
not something any check can resolve.

Every write in the chain has `source_type: chat`. That is correct and by design: the server
never parses files, so a human and a model read the PDF and submitted normalized records. The
problem is not how the extraction happened. **The problem is that the extraction left no
fingerprint of what it read.**

### F.1.1 Two consequences

**Drift is undetectable.** Nothing can compare the playbook as it is now against the playbook
the correlation was worked out against, because the latter was never captured.

**The correlation is not auditable.** Checking whether assertion IV.A.3 actually reflects what
the playbook says means a person reopening the PDF and redoing the reasoning. There is no
cheaper path, and at 123 assertions nobody will take the expensive one.

## F.2 Why the hash belongs to the caller, not the server

The obvious fix is for the server to hash the file. It should not.

Hashing is arguably not parsing, so it does not strictly violate the no-file-parsing boundary.
But it would give the server filesystem access to arbitrary paths, which is a materially larger
capability than it has today and a poor trade for one check.

The existing pattern already solves this. `document_set_snapshot.source` is
`'harvey_api' | 'manual'`: an observation can be made by the server or submitted by the caller.
Specification freshness should be caller-submitted only. Claude computes the digest of the file
it just read and submits it alongside the records, exactly as it submits everything else.

This keeps the boundary intact and costs nothing, because the caller is already holding the file
open at the moment the correlation is done.

## F.3 Schema delta

Additive, mirroring `document_set_snapshot`. Migration number depends on ordering against the
contract-review extension and the evaluation fields; call it **4, 5 or 6**.

```sql
ALTER TABLE requirement_source ADD COLUMN content_hash  TEXT;  -- caller-computed digest
ALTER TABLE requirement_source ADD COLUMN hash_algo     TEXT;  -- 'sha256'
ALTER TABLE requirement_source ADD COLUMN observed_at   TEXT;  -- when the digest was taken
ALTER TABLE requirement_source ADD COLUMN observed_by   TEXT CHECK (observed_by IN ('manual','caller'));

-- which edition the current correlation was actually worked out against
ALTER TABLE memo_outline ADD COLUMN source_hash TEXT;
```

`memo_outline.source_hash` is the load-bearing one. `requirement_source.content_hash` records
what the specification is *now*; `memo_outline.source_hash` records what it was *when the
correlation was written*. A check compares the two. Without the second column the first only
tells you the file exists, which you knew.

Everything is nullable, so nothing existing breaks. The current outline will carry a NULL
`source_hash` forever, which is honest: we genuinely do not know which edition it was derived
from.

## F.4 The check

Belongs in the existing `requirements` family of `suite_check`. No new family.

| Code | Fires when | Observation |
| --- | --- | --- |
| `SPEC_UNRECORDED` | source has no `content_hash` | The specification has no recorded digest, so a revision to it cannot be detected. |
| `SPEC_MOVED` | `requirement_source.content_hash` ≠ `memo_outline.source_hash` | The specification has changed since the correlation was worked out against it. |
| `SPEC_UNOBSERVED` | `observed_at` older than the correlation, or absent | The specification has not been re-observed since the correlation was written. |

Findings, not verdicts, in the house style: each states the fact and attaches the two digests
and their dates as evidence. Whether a revised playbook actually invalidates a given assertion
is a legal judgment, and often the answer is no. The system's job is to stop the question from
going unasked.

**Today the corpus would emit exactly one finding**, `SPEC_UNRECORDED`, against the one source
row. That is the correct output and a fair description of where things stand.

## F.5 What this does not solve

**It detects that the specification moved, not what moved in it.** A one-line typo fix and a
restructured Section 3 produce the same finding. Diffing editions would need the text of both,
which means storing the specification, which is a much larger decision about whether this server
holds source documents at all. It currently holds none, deliberately.

**It cannot retroactively date the current correlation.** v5 will carry a NULL `source_hash`.
The first honest hash is the next one somebody takes.

**It does nothing about per-assertion staleness.** A revised playbook marks the whole correlation
as needing review, not the eleven assertions actually affected. Narrowing that needs the diff
above, so it inherits the same blocker.

## F.6 Open questions

1. **Is the playbook a vendor artifact that will actually be revised?** The whole case rests on
   yes. If that document is effectively frozen, this is ceremony and the effort belongs in
   evaluation instead. Worth checking before building, and cheap to check.
2. **Does the same treatment belong on `table_instructions`?** Harvey omits those from its own
   exports, so the copy here is the only one. That makes it a specification of a kind, with the
   same drift exposure and no watcher.
3. **Superseded bindings accumulate.** `assertion_source` holds 1,373 rows against 364 in the
   current outline, because `memo_outline_set` replaces rather than updates and old versions are
   retained. That is probably right, since it preserves history, but nothing prunes them and
   coverage reads only the current outline. Worth an explicit decision rather than leaving it as
   a side effect.
