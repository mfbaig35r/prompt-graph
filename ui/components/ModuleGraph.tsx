"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { ArrowUpRight, Maximize2, Minus, Plus, RotateCcw } from "lucide-react";
import { Term } from "@/components/Tip";
import { GLOSSARY } from "@/lib/glossary";
import type { TableGraph } from "@/lib/api";

const NODE_W = 184;
const NODE_H = 42;
const ROW_H = 60;
const COL_GAP = 116;
const PAD = 26;
const PAD_BOTTOM = 40;

const ROLE_COLOR: Record<string, string> = {
  orientation: "var(--accent)",
  extraction: "var(--ok)",
  validation: "var(--warn)",
  reconciliation: "var(--violet)",
  human_review: "var(--stop)",
};

export function ModuleGraph({ g, base }: { g: TableGraph; base: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const scroller = useRef<HTMLDivElement>(null);

  const focus = hover ?? picked;

  const { placed, width, height, isolated } = useMemo(() => {
    const linked = g.nodes.filter((n) => !n.isolated);
    const isolated = g.nodes.filter((n) => n.isolated);
    const byLevel = new Map<number, typeof linked>();
    for (const n of linked) byLevel.set(n.level, [...(byLevel.get(n.level) ?? []), n]);
    const levels = [...byLevel.keys()].sort((a, b) => a - b);

    const order = new Map<number, number>();
    for (const l of levels) {
      byLevel.get(l)!.sort((a, b) => a.position - b.position);
      byLevel.get(l)!.forEach((n, i) => order.set(n.id, i));
    }
    const up = new Map<number, number[]>();
    const down = new Map<number, number[]>();
    for (const e of g.edges) {
      up.set(e.to, [...(up.get(e.to) ?? []), e.from]);
      down.set(e.from, [...(down.get(e.from) ?? []), e.to]);
    }
    for (let pass = 0; pass < 3; pass++) {
      for (const l of levels) {
        const col = byLevel.get(l)!;
        const bary = (id: number) => {
          const nb = pass % 2 === 0 ? (up.get(id) ?? []) : (down.get(id) ?? []);
          return nb.length ? nb.reduce((s, x) => s + (order.get(x) ?? 0), 0) / nb.length : (order.get(id) ?? 0);
        };
        col.sort((a, b) => bary(a.id) - bary(b.id));
        col.forEach((n, i) => order.set(n.id, i));
      }
    }

    const placed = new Map<number, { x: number; y: number; n: (typeof linked)[number] }>();
    for (const l of levels)
      byLevel.get(l)!.forEach((n, i) => {
        placed.set(n.id, { x: PAD + l * (NODE_W + COL_GAP), y: PAD + i * ROW_H, n });
      });
    const rows = Math.max(...levels.map((l) => byLevel.get(l)!.length), 1);
    return {
      placed,
      isolated,
      width: PAD * 2 + levels.length * NODE_W + Math.max(0, levels.length - 1) * COL_GAP,
      height: PAD + PAD_BOTTOM + rows * ROW_H,
    };
  }, [g]);

  const connected = useMemo(() => {
    if (focus === null) return null;
    const s = new Set<number>([focus]);
    for (const e of g.edges) {
      if (e.from === focus) s.add(e.to);
      if (e.to === focus) s.add(e.from);
    }
    return s;
  }, [focus, g.edges]);

  const sel = focus !== null ? placed.get(focus)?.n : undefined;
  const selUp = focus !== null ? g.edges.filter((e) => e.to === focus).length : 0;
  const selDown = focus !== null ? g.edges.filter((e) => e.from === focus).length : 0;

  const fit = () => {
    const w = scroller.current?.clientWidth ?? width;
    setZoom(Math.min(1, Math.max(0.4, (w - 24) / width)));
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_252px]">
      <div className="card relative overflow-hidden">
        <div className="absolute bottom-12 right-3 z-10 flex items-center gap-1 rounded-lg border p-1"
             style={{ background: "var(--surface)", borderColor: "var(--border-2)", boxShadow: "var(--shadow)" }}>
          <IconBtn onClick={() => setZoom((z) => Math.min(1.6, z + 0.15))} label="Zoom in"><Plus size={13} /></IconBtn>
          <IconBtn onClick={() => setZoom((z) => Math.max(0.4, z - 0.15))} label="Zoom out"><Minus size={13} /></IconBtn>
          <IconBtn onClick={fit} label="Fit"><Maximize2 size={12} /></IconBtn>
          <IconBtn onClick={() => { setZoom(1); setPicked(null); }} label="Reset"><RotateCcw size={12} /></IconBtn>
        </div>

        <div
          ref={scroller}
          className="canvas overflow-auto"
          style={{
            maxHeight: 600,
            maskImage: "linear-gradient(to bottom, #000 calc(100% - 26px), transparent 100%)",
            WebkitMaskImage: "linear-gradient(to bottom, #000 calc(100% - 26px), transparent 100%)",
          }}
        >
          <div
            className="relative"
            style={{ width: width * zoom, height: height * zoom }}
            onClick={() => setPicked(null)}
          >
            <div style={{ width, height, transform: `scale(${zoom})`, transformOrigin: "top left" }} className="relative">
              <EdgeLayer g={g} placed={placed} focus={focus} width={width} height={height} highlighted={false} />

              {[...placed.values()].map(({ x, y, n }) => {
                const dim = connected !== null && !connected.has(n.id);
                const isFocus = focus === n.id;
                const color = ROLE_COLOR[n.role ?? ""] ?? "var(--border-2)";
                return (
                  <button
                    key={n.id}
                    onMouseEnter={() => setHover(n.id)}
                    onMouseLeave={() => setHover(null)}
                    onClick={(ev) => { ev.stopPropagation(); setPicked(picked === n.id ? null : n.id); }}
                    className="absolute rounded-lg border px-2.5 text-left"
                    style={{
                      left: x, top: y, width: NODE_W, height: NODE_H,
                      background: isFocus ? "var(--accent-soft)" : "var(--surface)",
                      // One uniform hairline in the role colour. Focus is a ring outside the
                      // border, so the colour coding survives selection instead of being
                      // overwritten by it.
                      borderColor: color,
                      opacity: dim ? 0.28 : 1,
                      transition: "opacity 90ms, background 90ms",
                    }}
                    title={
                      `${n.name} · ${n.native_type}${n.role ? ` · ${n.role}` : ""}` +
                      (n.role && GLOSSARY[n.role] ? `\n\n${GLOSSARY[n.role].title}: ${GLOSSARY[n.role].body}` : "")
                    }
                  >
                    <div className="truncate pt-[5px] text-[11.5px] font-medium leading-tight">{n.name}</div>
                    <div className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wide" style={{ color: "var(--text-3)" }}>
                      <span className="truncate">{n.native_type}</span>
                      {n.degree > 3 && <span className="mono ml-auto shrink-0 normal-case">{n.degree}</span>}
                    </div>
                  </button>
                );
              })}

              {/* Highlighted edges are re-drawn above the nodes. Behind them, a line crossing a
                  dimmed box is overlaid by that box's background and appears to change tone
                  halfway along, which makes a traced path hard to follow. */}
              <EdgeLayer g={g} placed={placed} focus={focus} width={width} height={height} highlighted />
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t px-5 py-2.5 text-[11.5px]" style={{ color: "var(--text-3)" }}>
          {[...new Set(g.nodes.filter((n) => !n.isolated).map((n) => n.role ?? "unset"))].sort().map((r) => (
            <span key={r} className="flex items-center gap-1.5">
              <span className="h-2.5 w-[3px] rounded-full" style={{ background: ROLE_COLOR[r] ?? "var(--border-2)" }} />
              <Term k={r}>{r.replace(/_/g, " ")}</Term>
            </span>
          ))}
          <span className="ml-auto">upstream left · <Term k="degree">number = references</Term></span>
        </div>
      </div>

      <aside className="card self-start overflow-hidden">
        <div className="flex items-center justify-between border-b px-4 py-3" style={{ background: "var(--surface-2)" }}>
          <span className="eyebrow">Selection</span>
          {sel && (
            <Link href={`${base}/c/${encodeURIComponent(sel.name)}`} className="flex items-center gap-1 text-[11.5px] hover:underline" style={{ color: "var(--accent)" }}>
              Open <ArrowUpRight size={11} />
            </Link>
          )}
        </div>
        {sel ? (
          <div className="px-4 py-3.5">
            <div className="text-[13px] font-semibold leading-tight">{sel.name}</div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <span className="pill" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>{sel.native_type}</span>
              {sel.role && (
                <span className="pill" style={{ background: "var(--surface-2)", color: ROLE_COLOR[sel.role] ?? "var(--text-2)" }}>
                  {sel.role.replace(/_/g, " ")}
                </span>
              )}
            </div>
            <dl className="mt-3 space-y-1.5 text-[12.5px]">
              <Row k="Depends on" v={selUp} />
              <Row k="Feeds" v={selDown} />
              <Row k="Level" v={sel.level + 1} />
            </dl>
          </div>
        ) : (
          <p className="px-4 py-3.5 text-[12.5px]" style={{ color: "var(--text-3)" }}>
            Hover a rule to trace it. Click to pin it.
          </p>
        )}

        {isolated.length > 0 && (
          <div className="border-t px-4 py-3.5">
            <div className="eyebrow mb-1.5"><Term k="not_referenced">Not referenced</Term> · {isolated.length}</div>
            <div className="flex flex-wrap gap-1">
              {isolated.map((n) => (
                <Link key={n.id} href={`${base}/c/${encodeURIComponent(n.name)}`} className="pill hover:underline" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>
                  {n.name}
                </Link>
              ))}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

function EdgeLayer({
  g, placed, focus, width, height, highlighted,
}: {
  g: TableGraph;
  placed: Map<number, { x: number; y: number }>;
  focus: number | null;
  width: number;
  height: number;
  highlighted: boolean;
}) {
  const edges = g.edges.filter((e) => {
    const on = focus !== null && (e.from === focus || e.to === focus);
    return highlighted ? on : !on;
  });
  if (!edges.length) return null;
  return (
    <svg
      width={width}
      height={height}
      className="pointer-events-none absolute inset-0"
      style={highlighted ? { zIndex: 5 } : undefined}
    >
      {edges.map((e, i) => {
        const a = placed.get(e.from), b = placed.get(e.to);
        if (!a || !b) return null;
        const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2;
        const x2 = b.x, y2 = b.y + NODE_H / 2;
        const dx = Math.max(30, (x2 - x1) / 2);
        return (
          <path
            key={i}
            d={`M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`}
            fill="none"
            stroke={highlighted ? "var(--accent)" : "var(--edge)"}
            strokeWidth={highlighted ? 1.9 : 1.2}
            opacity={highlighted || focus === null ? 1 : 0.15}
          />
        );
      })}
    </svg>
  );
}

function IconBtn({ onClick, label, children }: { onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <button onClick={onClick} aria-label={label} title={label}
      className="grid h-6 w-6 place-items-center rounded-md"
      style={{ color: "var(--text-2)" }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface-2)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
      {children}
    </button>
  );
}
function Row({ k, v }: { k: string; v: number }) {
  return (
    <div className="flex justify-between">
      <dt style={{ color: "var(--text-2)" }}>{k}</dt>
      <dd className="mono">{v}</dd>
    </div>
  );
}
