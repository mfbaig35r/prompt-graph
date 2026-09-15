"""suite_check: schema-level validation across the whole matter (requirements §8).

Families: prompts (stored-prompt lint), graph (cycles, references, ordering, control plane),
parameters (orphans, dangling bindings, unbound values), consistency (date/currency
patterns, entity names, duplicate concepts, Table Instructions).
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from . import lint
from .constants import FALLBACK_VOCABULARY, ROLE_RANK
from .findings import Finding
from .graph import find_cycles, load_graph
from .parameters import check_parameter
from .refs import referenced_names
from .service import (
    current_instructions,
    current_prompt,
    effective_standard,
    get_matter,
    get_table,
    lint_column,
    table_columns,
)

CHECK_FAMILIES: tuple[str, ...] = ("prompts", "graph", "parameters", "consistency")

_REF_CODES = {"REF_UNRESOLVED", "REF_FORWARD", "REF_SELF"}

# --- date and currency pattern tokens -------------------------------------------------

_DATE_TOKENS = [
    "YYYY-MM-DD",
    "YYYY/MM/DD",
    "DD/MM/YYYY",
    "MM/DD/YYYY",
    "DD-MM-YYYY",
    "MM-DD-YYYY",
    "DD.MM.YYYY",
    "YYYYMMDD",
    "Month D, YYYY",
    "Month DD, YYYY",
    "D Month YYYY",
    "DD Month YYYY",
    "MMMM D, YYYY",
    "D MMMM YYYY",
    "YYYY-MM",
    "MM/YYYY",
]
_DATE_RE = re.compile("|".join(re.escape(t) for t in sorted(_DATE_TOKENS, key=len, reverse=True)))
_CURRENCY_RE = re.compile(
    r"(?:(?:USD|US\$|EUR|GBP|CAD|AUD|CHF|JPY|\$|€|£)\s?\d[\d,]*(?:\.\d{1,2})?)"
    r"|(?:\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|CAD|AUD|CHF|JPY)\b)"
)


def _currency_style(sample: str) -> str:
    s = re.sub(r"\d", "9", sample)
    s = re.sub(r"9[9,]*9", lambda m: "9,999" if "," in m.group(0) else "9999", s)
    s = re.sub(r"\.9+", ".99", s)
    return s.strip()


# --- entity name variants -------------------------------------------------------------

_SUFFIXES = [
    "L.L.C.",
    "LLC",
    "L.P.",
    "LP",
    "L.L.P.",
    "LLP",
    "Inc.",
    "Inc",
    "Incorporated",
    "Corp.",
    "Corp",
    "Corporation",
    "Ltd.",
    "Ltd",
    "Limited",
    "PLC",
    "plc",
    "Co.",
    "Company",
    "GmbH",
    "S.A.",
    "SA",
    "N.V.",
    "NV",
    "B.V.",
    "BV",
    "AG",
    "Pty Ltd",
    "Pty. Ltd.",
    "S.à r.l.",
    "SARL",
    "Holdings",
]
_SUFFIX_ALT = "|".join(re.escape(s) for s in sorted(_SUFFIXES, key=len, reverse=True))


def _split_entity(name: str) -> tuple[str, str]:
    m = re.match(rf"^(.*?)[,\s]+({_SUFFIX_ALT})\.?$", name.strip())
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2)
    return name.strip(), ""


def entity_variants(text: str, exact_name: str) -> list[str]:
    """Occurrences of the entity's base name whose printed form differs from `exact_name`."""
    base, _suffix = _split_entity(exact_name)
    if len(base) < 4:
        return []
    base_re = r"\s+".join(re.escape(w) for w in base.split())
    pat = re.compile(rf"\b{base_re}(?:\s*,?\s*(?:{_SUFFIX_ALT})\.?)?", re.IGNORECASE)
    out: list[str] = []
    for m in pat.finditer(text):
        found = " ".join(m.group(0).split())
        # allow a trailing period on a suffix when the exact name has one, and vice versa
        if found == exact_name:
            continue
        if found.rstrip(".") == exact_name.rstrip(".") and found.lower() == exact_name.lower():
            continue
        if found not in out:
            out.append(found)
    return out


# --- name similarity ------------------------------------------------------------------

_STOP = {
    "the",
    "of",
    "and",
    "or",
    "a",
    "an",
    "in",
    "for",
    "to",
    "detail",
    "details",
    # Prepositions carry no subject matter, but counted as shared tokens they pull unrelated
    # names over the similarity threshold: "Acceleration on Change of Control" and "Survival on
    # Change of Control" are different provisions that agreed on "on", "change" and "control".
    "on",
    "at",
    "by",
    "with",
    "from",
    "under",
    "per",
    "as",
}

# Tokens that usually distinguish a genuinely different question rather than a renamed one:
# a plan's default versus one instrument's actual, a former name versus the current one.
_QUALIFIERS = {
    "default",
    "standard",
    "form",
    "primary",
    "secondary",
    "initial",
    "current",
    "former",
    "prior",
    "proposed",
    "maximum",
    "minimum",
}


def _tokens(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------------------


def suite_check(
    conn: sqlite3.Connection,
    matter: str,
    checks: list[str] | None = None,
    table: str | None = None,
) -> dict[str, Any]:
    m = get_matter(conn, matter)
    matter_id = int(m["id"])
    families = [c.strip().lower() for c in checks] if checks else list(CHECK_FAMILIES)
    unknown = [f for f in families if f not in CHECK_FAMILIES]
    families = [f for f in families if f in CHECK_FAMILIES]
    only_table_id: int | None = int(get_table(conn, matter_id, table)["id"]) if table else None

    tables = conn.execute(
        "SELECT * FROM review_table WHERE matter_id=? ORDER BY position, name", (matter_id,)
    ).fetchall()
    if only_table_id is not None:
        tables = [t for t in tables if int(t["id"]) == only_table_id]
    findings: dict[str, list[Finding]] = {f: [] for f in families}

    g = load_graph(conn, matter_id)

    # ---------------- prompts ----------------
    if "prompts" in families:
        for t in tables:
            for c in table_columns(conn, int(t["id"])):
                for f in lint_column(conn, c):
                    if f.code in _REF_CODES:
                        continue  # reported under graph
                    f.evidence = {**f.evidence, "table": t["name"]}
                    findings["prompts"].append(f)

    # ---------------- graph ----------------
    if "graph" in families:
        for cyc in find_cycles(g):
            names = [f"{g.nodes[n].table_name} / {g.nodes[n].name}" for n in cyc]
            if only_table_id is not None and not any(
                g.nodes[n].table_id == only_table_id for n in cyc
            ):
                continue
            findings["graph"].append(
                Finding(
                    "GRAPH_CYCLE",
                    "matter",
                    matter_id,
                    m["name"],
                    f"A dependency cycle runs through {len(cyc)} column(s).",
                    {"cycle": names + [names[0]]},
                )
            )
        for t in tables:
            cols = table_columns(conn, int(t["id"]), include_retired=True)
            names = [c["name"] for c in cols]
            pos = {c["name"].lower(): int(c["position"]) for c in cols}
            for c in cols:
                if c["status"] == "retired":
                    continue
                pv = current_prompt(conn, int(c["id"]))
                if pv is None:
                    continue
                resolved, unresolved = referenced_names(pv["text"], names)
                for u in unresolved:
                    findings["graph"].append(
                        Finding(
                            "REF_UNRESOLVED",
                            "column",
                            int(c["id"]),
                            c["name"],
                            f"The reference `@{u}` does not match any column in table '{t['name']}'.",
                            {"table": t["name"], "reference": u},
                        )
                    )
                for r in resolved:
                    if r.lower() == c["name"].lower():
                        findings["graph"].append(
                            Finding(
                                "REF_SELF",
                                "column",
                                int(c["id"]),
                                c["name"],
                                f"The prompt references its own column `@{r}`.",
                                {"table": t["name"]},
                            )
                        )
                    elif pos.get(r.lower(), 0) > int(c["position"]):
                        findings["graph"].append(
                            Finding(
                                "REF_FORWARD",
                                "column",
                                int(c["id"]),
                                c["name"],
                                f"The prompt references `@{r}`, which is positioned after this column in table '{t['name']}'.",
                                {
                                    "table": t["name"],
                                    "reference": r,
                                    "referenced_position": pos[r.lower()],
                                    "this_position": int(c["position"]),
                                },
                            )
                        )
        for nid, n in g.nodes.items():
            if n.status == "retired":
                continue
            if only_table_id is not None and n.table_id != only_table_id:
                continue
            for e in g.inc.get(nid, []):
                up = g.nodes[e.src]
                if up.status == "retired":
                    findings["graph"].append(
                        Finding(
                            "DEPENDENCY_ON_RETIRED",
                            "column",
                            nid,
                            n.name,
                            f"'{n.table_name} / {n.name}' depends on the retired column '{up.table_name} / {up.name}'.",
                            {"kind": e.kind, "upstream": up.name, "upstream_table": up.table_name},
                        )
                    )
                if n.role and up.role and ROLE_RANK[up.role] > ROLE_RANK[n.role]:
                    findings["graph"].append(
                        Finding(
                            "ROLE_ORDER_VIOLATION",
                            "column",
                            nid,
                            n.name,
                            f"A {n.role} column depends on '{up.name}', a {up.role} column, which is a later stage in the skill's staged pattern.",
                            {
                                "kind": e.kind,
                                "upstream": up.name,
                                "upstream_role": up.role,
                                "this_role": n.role,
                            },
                        )
                    )
            if n.native_type in ("FreeResponse", "Verbatim"):
                dependents = {
                    e.dst
                    for e in g.out.get(nid, [])
                    if e.kind == "intra_table_ref" and g.nodes[e.dst].status != "retired"
                }
                if len(dependents) >= 2:
                    findings["graph"].append(
                        Finding(
                            "CONTROL_PLANE_NARRATIVE",
                            "column",
                            nid,
                            n.name,
                            f"The {n.native_type} column '{n.name}' is referenced by {len(dependents)} downstream columns in '{n.table_name}'.",
                            {"dependents": sorted(g.nodes[d].name for d in dependents)},
                        )
                    )

    # ---------------- parameters ----------------
    if "parameters" in families:
        for p in conn.execute(
            "SELECT * FROM shared_parameter WHERE matter_id=? ORDER BY name", (matter_id,)
        ):
            for f in check_parameter(conn, p):
                if only_table_id is not None:
                    tid = f.evidence.get("table")
                    if f.subject_type == "table" and f.subject_id != only_table_id:
                        continue
                    if (
                        f.subject_type == "parameter"
                        and tid
                        and tid != next(t["name"] for t in tables)
                    ):
                        continue
                findings["parameters"].append(f)

    # ---------------- consistency ----------------
    if "consistency" in families:
        std = effective_standard(conn, matter_id)
        std_date = std.get("date_pattern")
        std_cur = std.get("currency_pattern")
        std_cur_style = _currency_style(std_cur) if std_cur else None
        date_seen: dict[str, list[str]] = {}
        cur_seen: dict[str, list[str]] = {}
        by_concept: dict[str, list[dict[str, Any]]] = {}
        by_name: dict[str, list[dict[str, Any]]] = {}
        all_cols: list[dict[str, Any]] = []

        for t in tables:
            ti = current_instructions(conn, int(t["id"]))
            cols = table_columns(conn, int(t["id"]))
            if cols and ti is None:
                findings["consistency"].append(
                    Finding(
                        "INSTRUCTIONS_MISSING",
                        "table",
                        int(t["id"]),
                        t["name"],
                        f"Table '{t['name']}' has {len(cols)} column(s) but no Table Instructions stored; Harvey exports omit them.",
                        {},
                    )
                )
            texts: list[tuple[str, str, str | None]] = []  # (site label, text, column name)
            if ti is not None:
                texts.append(("table_instructions", ti["text"], None))
                missing = [v for v in FALLBACK_VOCABULARY if v.lower() not in ti["text"].lower()]
                if missing:
                    findings["consistency"].append(
                        Finding(
                            "INSTRUCTIONS_VOCABULARY_INCOMPLETE",
                            "table",
                            int(t["id"]),
                            t["name"],
                            f"The Table Instructions of '{t['name']}' do not list every controlled fallback state.",
                            {"missing": missing, "version": int(ti["version"])},
                        )
                    )
                for ent in std.get("entities") or []:
                    for v in entity_variants(ti["text"], ent["name"]):
                        findings["consistency"].append(
                            Finding(
                                "ENTITY_NAME_VARIANT",
                                "table",
                                int(t["id"]),
                                t["name"],
                                f"The Table Instructions of '{t['name']}' print the entity as '{v}' where the matter standard has '{ent['name']}'.",
                                {
                                    "standard_name": ent["name"],
                                    "variant": v,
                                    "site": "table_instructions",
                                },
                            )
                        )
            for c in cols:
                pv = current_prompt(conn, int(c["id"]))
                if pv is None:
                    continue
                texts.append(("column_prompt", pv["text"], c["name"]))
                for ent in std.get("entities") or []:
                    for v in entity_variants(pv["text"], ent["name"]):
                        findings["consistency"].append(
                            Finding(
                                "ENTITY_NAME_VARIANT",
                                "column",
                                int(c["id"]),
                                c["name"],
                                f"The prompt of '{t['name']} / {c['name']}' prints the entity as '{v}' where the matter standard has '{ent['name']}'.",
                                {
                                    "standard_name": ent["name"],
                                    "variant": v,
                                    "site": "column_prompt",
                                    "table": t["name"],
                                },
                            )
                        )
                info = {
                    "table": t["name"],
                    "table_id": int(t["id"]),
                    "column": c["name"],
                    "column_id": int(c["id"]),
                    "native_type": c["native_type"],
                    "role": c["role"],
                    "options": json.loads(c["configured_options"])
                    if c["configured_options"]
                    else None,
                    "fallbacks": lint.fallback_terms_used(pv["text"]),
                    "concept": (c["concept"] or "").strip().lower() or None,
                }
                all_cols.append(info)
                if info["concept"]:
                    by_concept.setdefault(info["concept"], []).append(info)
                by_name.setdefault(c["name"].strip().lower(), []).append(info)
            for _site, text, cname in texts:
                where = f"{t['name']} / {cname}" if cname else f"{t['name']} / Table Instructions"
                for tok in set(_DATE_RE.findall(text)):
                    date_seen.setdefault(tok, []).append(where)
                for sample in set(_CURRENCY_RE.findall(text)):
                    cur_seen.setdefault(_currency_style(sample), []).append(where)

        # Date patterns
        if std_date:
            for tok, sites in date_seen.items():
                if tok != std_date:
                    findings["consistency"].append(
                        Finding(
                            "DATE_PATTERN_DIVERGENT",
                            "matter",
                            matter_id,
                            m["name"],
                            f"The date pattern `{tok}` appears in {len(sites)} place(s) where the standard is `{std_date}`.",
                            {"pattern": tok, "standard": std_date, "sites": sorted(set(sites))},
                        )
                    )
        elif len(date_seen) > 1:
            findings["consistency"].append(
                Finding(
                    "DATE_PATTERN_DIVERGENT",
                    "matter",
                    matter_id,
                    m["name"],
                    f"{len(date_seen)} different date patterns are in use and no standard pattern is set.",
                    {"patterns": {k: sorted(set(v)) for k, v in date_seen.items()}},
                )
            )
        # Currency patterns
        if std_cur_style:
            for style, sites in cur_seen.items():
                if style != std_cur_style:
                    findings["consistency"].append(
                        Finding(
                            "CURRENCY_PATTERN_DIVERGENT",
                            "matter",
                            matter_id,
                            m["name"],
                            f"The currency style `{style}` appears in {len(sites)} place(s) where the standard is `{std_cur}`.",
                            {"style": style, "standard": std_cur, "sites": sorted(set(sites))},
                        )
                    )
        elif len(cur_seen) > 1:
            findings["consistency"].append(
                Finding(
                    "CURRENCY_PATTERN_DIVERGENT",
                    "matter",
                    matter_id,
                    m["name"],
                    f"{len(cur_seen)} different currency styles are in use and no standard pattern is set.",
                    {"styles": {k: sorted(set(v)) for k, v in cur_seen.items()}},
                )
            )

        # Same concept, divergent names or rules (explicit tags first, then identical names).
        def divergence(group: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "native_types": sorted({x["native_type"] for x in group}),
                "option_sets": sorted(
                    {json.dumps(x["options"]) for x in group if x["options"] is not None}
                ),
                "fallback_sets": sorted({json.dumps(x["fallbacks"]) for x in group}),
            }

        seen_pairs: set[tuple[int, int]] = set()
        for concept, group in by_concept.items():
            if len({x["table_id"] for x in group}) < 2:
                continue
            names = sorted({x["column"] for x in group})
            if len(names) > 1:
                findings["consistency"].append(
                    Finding(
                        "CONCEPT_NAME_VARIANT",
                        "matter",
                        matter_id,
                        m["name"],
                        f"The concept '{concept}' is extracted under {len(names)} different column names across tables.",
                        {
                            "concept": concept,
                            "columns": [f"{x['table']} / {x['column']}" for x in group],
                        },
                    )
                )
            d = divergence(group)
            if (
                len(d["native_types"]) > 1
                or len(d["option_sets"]) > 1
                or len(d["fallback_sets"]) > 1
            ):
                findings["consistency"].append(
                    Finding(
                        "CONCEPT_DIVERGENT_RULES",
                        "matter",
                        matter_id,
                        m["name"],
                        f"The concept '{concept}' is extracted with different types, options, or fallback states across tables.",
                        {
                            "concept": concept,
                            "columns": [f"{x['table']} / {x['column']}" for x in group],
                            **d,
                        },
                    )
                )
            for x in group:
                for y in group:
                    if x["column_id"] < y["column_id"]:
                        seen_pairs.add((x["column_id"], y["column_id"]))
        for group in by_name.values():
            if len({x["table_id"] for x in group}) < 2:
                continue
            if all(x["concept"] for x in group) and len({x["concept"] for x in group}) == 1:
                continue  # handled above
            d = divergence(group)
            if (
                len(d["native_types"]) > 1
                or len(d["option_sets"]) > 1
                or len(d["fallback_sets"]) > 1
            ):
                findings["consistency"].append(
                    Finding(
                        "CONCEPT_DIVERGENT_RULES",
                        "matter",
                        matter_id,
                        m["name"],
                        f"Columns named '{group[0]['column']}' in {len(group)} tables use different types, options, or fallback states.",
                        {"columns": [f"{x['table']} / {x['column']}" for x in group], **d},
                    )
                )
        # Similar names without a shared concept tag (heuristic).
        #
        # Compare distinct NAMES, not column instances. Comparing instances emitted one finding
        # per module pair, so a name used in 21 modules produced 21 identical findings about the
        # same concept. Names that link transitively are one cluster and one finding: `Governing
        # Law` and `Jurisdiction and Governing Law` and any third variant are one observation
        # about one concept, not three pairwise ones.
        by_lower: dict[str, list[dict[str, Any]]] = {}
        for c in all_cols:
            by_lower.setdefault(c["column"].strip().lower(), []).append(c)
        # A name is a candidate unless every instance of it already carries a concept tag, in
        # which case the explicit path above owns it.
        candidates = sorted(k for k, g in by_lower.items() if not all(x["concept"] for x in g))
        toks = {k: _tokens(k) for k in candidates}

        links: list[tuple[str, str]] = []
        parent: dict[str, str] = {k: k for k in candidates}

        def find(a: str) -> str:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for i, a in enumerate(candidates):
            for b in candidates[i + 1 :]:
                if len(toks[a]) < 2 or len(toks[b]) < 2:
                    continue
                if _jaccard(toks[a], toks[b]) < 0.6:
                    continue
                links.append((a, b))
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

        clusters: dict[str, list[str]] = {}
        for k in candidates:
            if any(k in pair for pair in links):
                clusters.setdefault(find(k), []).append(k)

        for members in clusters.values():
            if len(members) < 2:
                continue
            cols = [c for name in members for c in by_lower[name]]
            if len({c["table_id"] for c in cols}) < 2:
                continue
            display = sorted({c["column"] for c in cols})
            # A cluster is weaker evidence when its members differ in role, or when what
            # separates the names is a qualifier: those usually mark a different question
            # rather than the same one renamed.
            diff_tokens: set[str] = set()
            for name in members:
                diff_tokens |= toks[name] - set.intersection(*(toks[n] for n in members))
            roles = {c["role"] for c in cols if c["role"]}
            linked = {frozenset(pair) for pair in links}
            clique = all(
                frozenset((a, b)) in linked for i, a in enumerate(members) for b in members[i + 1 :]
            )
            reasons = []
            if not clique:
                reasons.append("members are joined transitively, not all to each other")
            if diff_tokens & _QUALIFIERS:
                reasons.append(
                    f"qualifier {sorted(diff_tokens & _QUALIFIERS)!r} distinguishes them"
                )
            # Only a role split across the orientation boundary counts. Orientation runs first
            # and establishes what the row is, so orientation-versus-substantive is a real
            # signal that two questions differ. Extraction versus validation versus
            # reconciliation are all substantive and routinely drift on the same question:
            # treating that as evidence downgraded the best finding in the corpus, where
            # `Owner Matches Target Entity` and `Holder Matches Target Entity` ask one question
            # and happen to be tagged extraction and reconciliation.
            if "orientation" in roles and roles - {"orientation"}:
                reasons.append(
                    f"one member is orientation, the others are {', '.join(sorted(roles - {'orientation'}))}"
                )
            confidence = "possible" if reasons else "strong"
            findings["consistency"].append(
                Finding(
                    "CONCEPT_NAME_VARIANT",
                    "matter",
                    matter_id,
                    m["name"],
                    f"{len(display)} similar column names across {len({c['table_id'] for c in cols})} tables have no shared concept tag: "
                    + ", ".join(f"'{n}'" for n in display)
                    + ".",
                    {
                        "names": display,
                        "columns": [f"{c['table']} / {c['column']}" for c in cols],
                        "confidence": confidence,
                        "confidence_reasons": reasons,
                        "links": [[a, b] for a, b in links if find(a) == find(members[0])],
                        "heuristic": "token overlap",
                    },
                )
            )

    counts = {fam: len(v) for fam, v in findings.items()}
    by_code: dict[str, int] = {}
    for v in findings.values():
        for f in v:
            by_code[f.code] = by_code.get(f.code, 0) + 1
    return {
        "matter": m["name"],
        "table": table,
        "checks_run": families,
        "unknown_checks": unknown,
        "counts": counts,
        "by_code": dict(sorted(by_code.items())),
        "findings": [f for fam in families for f in findings[fam]],
    }
