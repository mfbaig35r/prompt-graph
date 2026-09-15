"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Term } from "@/components/Tip";
import { GLOSSARY } from "@/lib/glossary";
import type { TableGraph } from "@/lib/api";

const NODE_W = 188;
const NODE_H = 26;
const ROW_H = 34;
const COL_GAP = 96;
const PAD = 8;

const ROLE_COLOR: Record<string, string> = {
  orientation: "var(--accent)",
  extraction: "var(--ok)",
  validation: "var(--warn)",
  reconciliation: "#8a63d2",
  human_review: "var(--stop)",
};

export function ModuleGraph({ g, base }: { g: TableGraph; base: string }) {
  const [hover, setHover] = useState<number | null>(null);

  const { placed, width, height, isolated } = useMemo(() => {
    const linked = g.nodes.filter((n) => !n.isolated);
    const isolated = g.nodes.filter((n) => n.isolated);
    const byLevel = new Map<number, typeof linked>();
    for (const n of linked) {
      const a = byLevel.get(n.level) ?? [];
      a.push(n);
      byLevel.set(n.level, a);
    }
    const levels = [...byLevel.keys()].sort((a, b) => a - b);

    // Seed each column by position, then run barycentre passes so edges cross less.
    const order = new Map<number, number>();
    for (const l of levels) {
      byLevel.get(l)!.sort((a, b) => a.position - b.position);
      byLevel.get(l)!.forEach((n, i) => order.set(n.id, i));
    }
    const upstream = new Map<number, number[]>();
    const downstream = new Map<number, number[]>();
    for (const e of g.edges) {
      upstream.set(e.to, [...(upstream.get(e.to) ?? []), e.from]);
      downstream.set(e.from, [...(downstream.get(e.from) ?? []), e.to]);
    }
    for (let pass = 0; pass < 3; pass++) {
      for (const l of levels) {
        const col = byLevel.get(l)!;
        const bary = (id: number) => {
          const nbrs = pass % 2 === 0 ? (upstream.get(id) ?? []) : (downstream.get(id) ?? []);
          if (!nbrs.length) return order.get(id) ?? 0;
          return nbrs.reduce((s, x) => s + (order.get(x) ?? 0), 0) / nbrs.length;
        };
        col.sort((a, b) => bary(a.id) - bary(b.id));
        col.forEach((n, i) => order.set(n.id, i));
      }
    }

    const placed = new Map<number, { x: number; y: number; n: (typeof linked)[number] }>();
    for (const l of levels) {
      byLevel.get(l)!.forEach((n, i) => {
        placed.set(n.id, { x: PAD + l * (NODE_W + COL_GAP), y: PAD + i * ROW_H, n });
      });
    }
    const rows = Math.max(...levels.map((l) => byLevel.get(l)!.length), 1);
    return {
      placed,
      isolated,
      width: PAD * 2 + levels.length * NODE_W + Math.max(0, levels.length - 1) * COL_GAP,
      height: PAD * 2 + rows * ROW_H,
    };
  }, [g]);

  const connected = useMemo(() => {
    if (hover === null) return null;
    const s = new Set<number>([hover]);
    for (const e of g.edges) {
      if (e.from === hover) s.add(e.to);
      if (e.to === hover) s.add(e.from);
    }
    return s;
  }, [hover, g.edges]);

  return (
    <div>
      <div className="card overflow-x-auto p-1">
        <div className="relative" style={{ width, height }}>
          <svg width={width} height={height} className="absolute inset-0 pointer-events-none">
            {g.edges.map((e, i) => {
              const a = placed.get(e.from);
              const b = placed.get(e.to);
              if (!a || !b) return null;
              const x1 = a.x + NODE_W;
              const y1 = a.y + NODE_H / 2;
              const x2 = b.x;
              const y2 = b.y + NODE_H / 2;
              const dx = Math.max(28, (x2 - x1) / 2);
              const on = hover === null || e.from === hover || e.to === hover;
              return (
                <path
                  key={i}
                  d={`M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`}
                  fill="none"
                  stroke={on && hover !== null ? "var(--accent)" : "var(--edge)"}
                  strokeWidth={on && hover !== null ? 1.7 : 1.15}
                  opacity={on ? 1 : 0.18}
                />
              );
            })}
          </svg>
          {[...placed.values()].map(({ x, y, n }) => {
            const dim = connected !== null && !connected.has(n.id);
            return (
              <Link
                key={n.id}
                href={`${base}/c/${encodeURIComponent(n.name)}`}
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover(null)}
                className="absolute flex items-center gap-1.5 rounded-md border px-2 text-[11.5px]"
                style={{
                  left: x,
                  top: y,
                  width: NODE_W,
                  height: NODE_H,
                  background: hover === n.id ? "var(--accent-soft)" : "var(--surface)",
                  borderColor: hover === n.id ? "var(--accent)" : "var(--border)",
                  opacity: dim ? 0.3 : 1,
                  transition: "opacity 90ms, background 90ms",
                }}
                title={
                  `${n.name} · ${n.native_type}${n.role ? ` · ${n.role}` : ""}` +
                  (n.role && GLOSSARY[n.role] ? `\n\n${GLOSSARY[n.role].title}: ${GLOSSARY[n.role].body}` : "")
                }
              >
                <span
                  className="h-3 w-[3px] shrink-0 rounded-full"
                  style={{ background: ROLE_COLOR[n.role ?? ""] ?? "var(--border-2)" }}
                />
                <span className="truncate">{n.name}</span>
                {n.degree > 3 && (
                  <span className="mono ml-auto shrink-0 text-[10px]" style={{ color: "var(--text-3)" }}>
                    {n.degree}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]" style={{ color: "var(--text-3)" }}>
        {[...new Set(g.nodes.filter((n) => !n.isolated).map((n) => n.role ?? "unset"))]
          .sort()
          .map((r) => (
            <span key={r} className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-[3px] rounded-full"
                style={{ background: ROLE_COLOR[r] ?? "var(--border-2)" }}
              />
              <Term k={r}>{r.replace(/_/g, " ")}</Term>
            </span>
          ))}
        <span className="ml-auto">upstream left, downstream right · <Term k="degree">number = total references</Term></span>
      </div>

      {isolated.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11.5px]" style={{ color: "var(--text-3)" }}>
          <span><Term k="not_referenced">Not referenced</Term> ({isolated.length}):</span>
          {isolated.map((n) => (
            <Link
              key={n.id}
              href={`${base}/c/${encodeURIComponent(n.name)}`}
              className="rounded border px-1.5 py-0.5 hover:underline"
              style={{ borderColor: "var(--border)" }}
            >
              {n.name}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
