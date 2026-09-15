"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, GitCompare, Shuffle } from "lucide-react";
import { Term } from "@/components/Tip";
import { useLiveVersion } from "@/components/Live";
import {Card, Eyebrow, PageHeader, Panel, Pill, Stat} from "@/components/ui";
import { getConcepts, type Concepts, type Divergence } from "@/lib/api";

export default function ConceptsPage() {
  const matter = decodeURIComponent(useParams<{ matter: string }>().matter);
  const [d, setD] = useState<Concepts | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    getConcepts(matter)
      .then((r) => {
        setD(r);
        setOpen((o) => (o.size ? o : new Set(r.divergent.slice(0, 1).map((x) => x.name))));
      })
      .catch((e) => setErr(String(e)));
  }, [matter]);
  useEffect(load, [load]);
  useLiveVersion(load);

  if (err) return <main className="px-8 py-8" style={{ color: "var(--stop)" }}>{err}</main>;
  if (!d) return <main className="px-8 py-8" style={{ color: "var(--text-3)" }}>Loading…</main>;

  const base = `/m/${encodeURIComponent(matter)}`;
  const toggle = (k: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  return (
    <main className="px-8 py-7">
      <PageHeader
        crumbs={[{ label: matter, href: base }, { label: "Consistency" }]}
        title="Cross-module consistency"
        description="Where the same legal concept is handled differently in different modules. Every row below is a place a reviewer could get two different answers to the same question depending on which module ran."
      />

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat termKey="divergent_rules" label="Same name, different rules" value={d.counts.divergent} tone={d.counts.divergent ? "warn" : undefined} icon={GitCompare} />
        <Stat termKey="name_variant" label="Similar names, no shared concept" value={d.counts.name_variants} tone={d.counts.name_variants ? "warn" : undefined} icon={Shuffle} />
        <Stat label="Other consistency findings" value={d.counts.other} />
      </div>

      <Eyebrow icon={GitCompare}>Same name, different rules · {d.divergent.length}</Eyebrow>
      <div className="space-y-2">
        {d.divergent.map((x) => (
          <DivergenceCard key={x.name} x={x} base={base} open={open.has(x.name)} onToggle={() => toggle(x.name)} />
        ))}
      </div>

      <div className="mt-8"><Panel title={`Similar names, no shared concept · ${d.name_variants.length}`} icon={Shuffle}>
        {d.name_variants.map((v, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 border-b px-4 py-2 text-[12.5px] last:border-b-0">
            {v.members.map((mm, j) => (
              <span key={j} className="flex items-center gap-2">
                {j > 0 && <span style={{ color: "var(--text-3)" }}>vs</span>}
                <Link
                  href={`${base}/t/${encodeURIComponent(mm.table)}/c/${encodeURIComponent(mm.column)}`}
                  className="hover:underline"
                >
                  <span className="font-medium">{mm.column}</span>
                  <span style={{ color: "var(--text-3)" }}> · {mm.table}</span>
                </Link>
              </span>
            ))}
          </div>
        ))}
      </Panel></div>
    </main>
  );
}

function DivergenceCard({
  x, base, open, onToggle,
}: { x: Divergence; base: string; open: boolean; onToggle: () => void }) {
  return (
    <Card className="overflow-hidden">
      <button onClick={onToggle} className="rowlink flex w-full items-center gap-3 px-4 py-2.5 text-left">
        {open ? <ChevronDown size={14} style={{ color: "var(--text-3)" }} /> : <ChevronRight size={14} style={{ color: "var(--text-3)" }} />}
        <span className="font-medium">{x.name}</span>
        <Pill tone="warn">{x.members.length} modules</Pill>
        {x.distinct_option_sets > 1 && <Term k="distinct_option_sets" underline={false}><Pill tone="stop">{x.distinct_option_sets} different option sets</Pill></Term>}
        {x.native_types.map((t) => <Pill key={t}>{t}</Pill>)}
      </button>

      {open && (
        <div className="border-t">
          {x.shared_options.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5 border-b px-4 py-2" style={{ background: "var(--surface-2)" }}>
              <span className="eyebrow mb-0 mr-1"><Term k="agreed_by_all">Agreed by all</Term></span>
              {x.shared_options.map((o) => <Pill key={o} tone="ok">{o}</Pill>)}
            </div>
          ) : (
            <div className="border-b px-4 py-2 text-[12px]" style={{ background: "var(--surface-2)", color: "var(--text-3)" }}>
              {x.observation}
            </div>
          )}
          {x.members.map((mm, i) => (
            <div key={i} className="flex flex-col gap-1.5 border-b px-4 py-2.5 last:border-b-0 sm:flex-row sm:gap-4">
              <Link
                href={`${base}/t/${encodeURIComponent(mm.table)}/c/${encodeURIComponent(mm.column)}`}
                className="shrink-0 text-[12.5px] hover:underline sm:w-[260px]"
              >
                {mm.table}
              </Link>
              <div className="flex flex-wrap gap-1.5">
                {(mm.divergent_options ?? []).length > 0 ? (
                  mm.divergent_options!.map((o) => <Pill key={o} tone="stop">{o}</Pill>)
                ) : (
                  <span className="text-[12px]" style={{ color: "var(--text-3)" }}>
                    {mm.options ? "no options unique to this module" : "differs in fallback or wording, not options"}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
