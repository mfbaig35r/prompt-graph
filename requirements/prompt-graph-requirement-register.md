# prompt-graph — requirement register

**Extends:** `prompt-graph-mcp-requirements.md`, `prompt-graph-addendum-a.md`
**Date:** 2026-09-16
**Status:** BUILT 2026-09-16. Shipped as migration 3, not 4: the contract-review extension it
assumed would land first has not. Tools `requirements_ingest` and `requirement_set`, and a
`requirements` family in `suite_check`.

Records the external specification a review-table suite is built to satisfy, so that a playbook
prompt which maps to **no** table is a stored finding rather than a line in a spreadsheet.

---

## C.0 Why this belongs here

Prompt lint tests a rule. Evaluation tests a rule's answers. Neither can detect the failure
where every rule is correct and the suite still cannot support the deliverable, because that
failure is a property of the set, not of any member. Coverage is the only check that operates
on the whole, which is what makes it the most consequential one.

But coverage as it stands tests *this outline* against *these columns*, and the outline was
written by the same hand that wrote the columns. That is marking your own homework. A playbook
is the independent standard: correlating to it asks whether the memo being supported is the
right memo.

That completes a chain the server otherwise records only the back half of:

```
playbook requirement -> memo assertion -> column -> prompt -> cell
                        \____ recorded today ____/
```

**Consequence worth acting on separately.** `suite_check` runs four families: prompts, graph,
parameters, consistency. Coverage is not among them, and `table_readiness` composes
`suite_check`. So a table can currently read ready while supporting nothing the deliverable
needs. If correlation is the most consequential test, it belongs in the families.

---

## C.1 The shape of the real source material

Measured from the correlation worked out for one matter against a 103-page playbook, Section 3:

| | |
| --- | --- |
| Requirements | 25 |
| Layer 2 only, cross-document synthesis | 8 |
| Layer 1 only, a review table serves it | 7 |
| Layer 1 **and** Layer 2 | 4 |
| No table, external input | 4 |
| Split across parts with different dispositions | 2 |
| Name a serving table | 15 |
| Say "consumes …" rather than naming one | 10 |
| Tables with no requirement at all, justified elsewhere | 3 |
| Longest correlation note | 242 characters |

**Six of twenty-five decompose.** 3.4.7 is "Part A needs the buyer's checklist, Part B becomes
memo section IV.B". At 24% that is not an edge case, and it decides the schema: disposition
cannot live on the requirement.

The four `external` dispositions are the artifact worth storing. They are the findings that a
playbook prompt cannot be served by any review table, and why: it needs the deal team's input,
an external request list, or it is a process instruction rather than an extraction.

---

## C.2 Schema

Four tables.

**`requirement_source`** is the playbook as a citable artifact. The server currently holds no
reference to it at all, not a filename, edition or date, so a finding cannot say what it was
found against.

**`requirement`** is one numbered item: `ref` ("3.4.7"), title, note.

**`requirement_part`** carries the disposition, because a quarter of them split. `label` is
NULL for the common single-part case. An `external` part links to nothing and carries its
reason, which is the whole point of recording it.

**`requirement_link`** joins a part either to a `review_table` (`served_by`, `consumes`) or to
a `memo_section` (`produces`). Two CHECK constraints keep that honest: exactly one target, and
`produces` is the kind that points at a section.

---

## C.3 The reverse direction is computed, not stored

Tables serving no requirement are derived, exactly as `unsourced_columns` is on the coverage
report. In the measured set three tables have no Section 3 prompt and are justified instead
against the §4.2.1 representation package and §5/§6 deliverables. That is a real answer, not an
absence, and the report should say which requirement elsewhere justifies them rather than
listing them as orphans.

---

## C.4 Findings

- `REQUIREMENT_UNASSESSED`: imported, no disposition decided.
- `REQUIREMENT_EXTERNAL`: informational, and a deliberate boundary. It reads like
  `COV_JUDGMENT_BOUNDARY`: a thing no review table can serve, recorded so it is not mistaken
  for an oversight.
- `REQUIREMENT_SERVED_BY_NOTHING`: disposition `served`, no `served_by` link.
- `REQUIREMENT_SECTION_MISSING`: a `synthesis` part that produces a memo section which the
  current outline does not contain.
- `TABLE_SERVES_NO_REQUIREMENT`: computed, per C.3.

These belong in a `requirements` family of `suite_check`, alongside the coverage family C.0
argues for.

---

## C.5 Tools

- **`requirements_ingest`**: a source and its items in one call, the way `table_ingest` takes
  a table. Re-ingesting is safe: match on `(source, ref)`, leave unchanged items alone.
- **`requirement_set`**: disposition, reason and links for one requirement, by `ref`.
- The report is part of `suite_check`, not its own tool.

Two new tools, so 24.

---

## Migration 3 (numbered 4 in the proposal)

Numbered on the assumption migration 3 (the contract-review extension) lands first. If that one
does not ship, this becomes 3.

```sql
CREATE TABLE requirement_source (
    id          INTEGER PRIMARY KEY,
    matter_id   INTEGER NOT NULL REFERENCES matter(id),
    name        TEXT NOT NULL,
    citation    TEXT,                    -- filename, edition, page count: what was read
    version     TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (matter_id, name)
);

CREATE TABLE requirement (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES requirement_source(id),
    ref         TEXT NOT NULL,           -- "3.4.7"
    position    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (source_id, ref)
);

-- Disposition lives on a part, not on the requirement: a quarter of the real set splits, and
-- 3.4.7 is "Part A needs an external checklist, Part B is cross-document synthesis".
CREATE TABLE requirement_part (
    id              INTEGER PRIMARY KEY,
    requirement_id  INTEGER NOT NULL REFERENCES requirement(id),
    label           TEXT,                -- "Part A"; NULL when the requirement does not split
    position        INTEGER NOT NULL,
    disposition     TEXT NOT NULL
                    CHECK (disposition IN ('served', 'synthesis', 'external', 'unassessed')),
    reason          TEXT,                -- why external, or what the synthesis must do
    UNIQUE (requirement_id, position)
);

CREATE TABLE requirement_link (
    id          INTEGER PRIMARY KEY,
    part_id     INTEGER NOT NULL REFERENCES requirement_part(id),
    kind        TEXT NOT NULL CHECK (kind IN ('served_by', 'consumes', 'produces')),
    table_id    INTEGER REFERENCES review_table(id),
    section_id  INTEGER REFERENCES memo_section(id),
    note        TEXT,
    CHECK ((table_id IS NOT NULL) + (section_id IS NOT NULL) = 1),
    CHECK ((kind = 'produces') = (section_id IS NOT NULL)),
    UNIQUE (part_id, kind, table_id, section_id)
);
CREATE INDEX idx_requirement_source ON requirement(source_id, position);
CREATE INDEX idx_requirement_part ON requirement_part(requirement_id, position);
CREATE INDEX idx_requirement_link_part ON requirement_link(part_id);
CREATE INDEX idx_requirement_link_table ON requirement_link(table_id);
```

### Verification, 2026-09-16

Applied to a `.backup` copy of a real two-matter database (37 tables, 841 columns):

- `PRAGMA integrity_check` → `ok`; `PRAGMA foreign_key_check` → clean; row counts unchanged.
- The real 3.4.7 case models correctly: one requirement, Part A `external` with its reason and
  no links, Part B `synthesis` linked `consumes` → Contracts and `produces` → IV.B Contracts.
- All five constraint violations rejected: an invalid disposition; a link with both a table and
  a section; a link with neither; `produces` pointing at a table; `consumes` pointing at a
  section.

---

## Deliberately not in this

- **No import from the workbook.** The register is populated through the tools like everything
  else. A one-off script that reads the sheet is a migration aid, not part of the server.
- **No requirement text.** Only the reference, title and correlation note. The playbook's own
  prompt text is the vendor's copyrighted material and belongs in the source document, which
  `citation` points at.
- **No rep-package modelling.** The §4.2.1 representations are already stored as memo outline
  section IX. They are a deliverable, not a requirement source, and duplicating them here would
  create a second home for the same claims.

---

## Open decisions

**1. Firm asset, matter-scoped table.** A playbook belongs to the firm; the correlation belongs
to a matter. `requirement_source` is matter-scoped here, so the same 25 items are re-imported
per deal and their dispositions cannot be compared across matters. Firm-scoped source with
matter-scoped parts and links is the correct shape and is more work.

Recommendation: take the simple version, record the debt. Revisit when a second matter
correlates against the same playbook, which is the first moment the duplication costs anything.

**2. Twenty-five rows.** This is a lot of machinery for a set that size, and a spreadsheet is
not obviously the wrong tool. The case for building is that the `external` dispositions are the
most decision-relevant output of the whole exercise, and they currently live in a file that is
not versioned, is absent from `matter_export`, and goes stale silently the moment a table
changes. The case against is that if this only ever happens once, for one playbook, the sheet
is fine.

**3. The layer taxonomy is one reading.** Layer 1 / Layer 2 was a judgment made during a
correlation exercise, and `CHECK (disposition IN (...))` freezes it into the schema. `served`,
`synthesis`, `external` and `unassessed` are chosen to be one step more general than the
playbook's own vocabulary so that a differently structured source still fits.

**4. Coverage is not a `suite_check` family.** Raised in C.0 and separable from everything
else here. It is arguably the highest-value small change in this document.
