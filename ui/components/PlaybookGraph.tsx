"use client";

import { useMemo, useState } from "react";
import type { PlaybookRule } from "@/lib/api";

/** Playbook dependencies are not a DAG and must not be drawn as one.
 *
 *  A review table's graph is execution order: one column reads another's answer, so levels mean
 *  something. Playbook rules all evaluate in parallel, and the edges are legal relationships
 *  instead. Aggregate exposure is symmetric and forms near-cliques (eight liability provisions,
 *  thirteen edges between them), which a layered layout would render as nonsense.
 *
 *  So: connected components as clusters, and inside each an arc diagram, which keeps long rule
 *  names readable in a way a node-link circle does not. What a reader should take away is which
 *  provisions are one decision, not which runs first. */

const REASON = {
  "aggregate exposure": { color: "var(--stop)", label: "aggregate exposure", note: "assessed as one set" },
  "trade-off": { color: "var(--warn)", label: "trade-off", note: "conceding here depends on that" },
  definition: { color: "var(--accent)", label: "definition", note: "a change here moves the other" },
  ordering: { color: "var(--ok)", label: "ordering", note: "one is a gate on the other" },
} as const;
type Reason = keyof typeof REASON;

function norm(s: string | null): Reason {
  const k = (s ?? "").toLowerCase().replace(/_/g, " ").trim();
  return k in REASON ? (k as Reason) : "definition";
}

type Edge = { from: string; to: string; reason: Reason };

function components(ids: string[], edges: Edge[]) {
  const adj = new Map<string, Set<string>>(ids.map((i) => [i, new Set<string>()]));
  for (const e of edges) {
    adj.get(e.from)?.add(e.to);
    adj.get(e.to)?.add(e.from);
  }
  const seen = new Set<string>();
  const out: string[][] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    const stack = [id];
    const comp: string[] = [];
    while (stack.length) {
      const x = stack.pop()!;
      if (seen.has(x)) continue;
      seen.add(x);
      comp.push(x);
      for (const n of adj.get(x) ?? []) if (!seen.has(n)) stack.push(n);
    }
    out.push(comp);
  }
  return out.sort((a, b) => b.length - a.length);
}

const ROW = 30;
const GUTTER = 132;

function Cluster({
  ids,
  edges,
  label,
  sel,
  onSel,
}: {
  ids: string[];
  edges: Edge[];
  label: Map<string, string>;
  sel: string | null;
  onSel: (id: string | null) => void;
}) {
  const y = (id: string) => ids.indexOf(id) * ROW + ROW / 2;
  const inner = edges.filter((e) => ids.includes(e.from) && ids.includes(e.to));
  const h = ids.length * ROW;
  return (
    <div className="card overflow-hidden">
      <div className="flex items-stretch">
        <ul className="min-w-0 flex-1 py-0">
          {ids.map((id) => {
            const on = sel === id;
            const touching =
              sel !== null && inner.some((e) => (e.from === sel && e.to === id) || (e.to === sel && e.from === id));
            return (
              <li key={id} style={{ height: ROW }}>
                <button
                  onClick={() => onSel(on ? null : id)}
                  className="flex h-full w-full items-center gap-2 px-4 text-left"
                  style={{
                    background: on ? "var(--surface-2)" : "transparent",
                    opacity: sel === null || on || touching ? 1 : 0.35,
                  }}
                >
                  <span className="truncate text-[12px]">{label.get(id) ?? id}</span>
                </button>
              </li>
            );
          })}
        </ul>
        <svg width={GUTTER} height={h} className="shrink-0" style={{ background: "var(--bg-2)" }}>
          {inner.map((e, i) => {
            const y1 = y(e.from);
            const y2 = y(e.to);
            const span = Math.abs(y2 - y1);
            const x = 10 + Math.min(span / 2.1, GUTTER - 26);
            const dim = sel !== null && e.from !== sel && e.to !== sel;
            return (
              <path
                key={i}
                d={`M8,${y1} C${x},${y1} ${x},${y2} 8,${y2}`}
                fill="none"
                stroke={REASON[e.reason].color}
                strokeWidth={sel !== null && !dim ? 1.8 : 1.1}
                opacity={dim ? 0.12 : 0.75}
              />
            );
          })}
          {ids.map((id) => (
            <circle key={id} cx={8} cy={y(id)} r={2.5} fill="var(--text-3)" />
          ))}
        </svg>
      </div>
    </div>
  );
}

export function PlaybookGraph({ rules }: { rules: PlaybookRule[] }) {
  const [sel, setSel] = useState<string | null>(null);

  const { comps, edges, label, isolated } = useMemo(() => {
    const label = new Map<string, string>();
    for (const r of rules) if (r.rule_id) label.set(r.rule_id, r.name);
    const edges: Edge[] = [];
    for (const r of rules) {
      if (!r.rule_id) continue;
      for (const d of r.depends_on) {
        if (label.has(d.ref)) edges.push({ from: r.rule_id, to: d.ref, reason: norm(d.reason) });
      }
    }
    const all = components([...label.keys()], edges);
    return {
      edges,
      label,
      comps: all.filter((c) => c.length > 1),
      isolated: all.filter((c) => c.length === 1).flat(),
    };
  }, [rules]);

  if (edges.length === 0)
    return (
      <div className="card px-5 py-3.5 text-[12.5px]" style={{ color: "var(--text-2)" }}>
        No rule declares a dependency, so there is no graph to draw. That is not the same as the
        relationships being absent: the convention that records them lives in Guidance, and
        nothing here has used it.
      </div>
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11.5px]">
        {(Object.keys(REASON) as Reason[]).map((k) => (
          <span key={k} className="flex items-center gap-1.5" style={{ color: "var(--text-3)" }}>
            <i className="h-[2px] w-5" style={{ background: REASON[k].color }} />
            <span style={{ color: "var(--text-2)" }}>{REASON[k].label}</span>
            <span>· {REASON[k].note}</span>
          </span>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {comps.map((c) => (
          <div key={c[0]}>
            <div className="eyebrow mb-1.5">
              {c.length} rules · {edges.filter((e) => c.includes(e.from) && c.includes(e.to)).length} edges
            </div>
            <Cluster ids={c} edges={edges} label={label} sel={sel} onSel={setSel} />
          </div>
        ))}
      </div>

      {isolated.length > 0 && (
        <div>
          <div className="eyebrow mb-1.5">{isolated.length} rules declare no relationship</div>
          <div className="card flex flex-wrap gap-x-4 gap-y-1.5 px-4 py-3">
            {isolated.map((id) => (
              <span key={id} className="text-[12px]" style={{ color: "var(--text-3)" }}>
                {label.get(id)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
