"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { BookOpen, ChevronDown, ChevronRight, CircleCheck, CircleDashed, Scale, TriangleAlert, Unplug } from "lucide-react";
import { useLiveVersion } from "@/components/Live";
import { PageHeader, Panel, Pill, Stat } from "@/components/ui";
import { getCoverage, type Coverage, type CoverageAssertion } from "@/lib/api";

/** Status is computed, not stored. `nominally_covered` means sourced but never run, which is
 *  this matter's whole state until a run exists: a neutral fact, not a defect. Only
 *  `extraction_gap` means a real hole, so only it is allowed to read as one. */
const STATUS: Record<string, { label: string; tone: "ok" | "warn" | "stop" | "neutral" | "accent"; hint: string }> = {
  reliably_covered: { label: "reliably covered", tone: "ok", hint: "sourced, run, and passing" },
  nominally_covered: { label: "sourced", tone: "accent", hint: "has a source, not yet run against documents" },
  extraction_gap: { label: "gap", tone: "stop", hint: "no column supplies evidence for this" },
  judgment_boundary: { label: "attorney judgment", tone: "neutral", hint: "no document can establish this; the attorney supplies it" },
};

export default function CoveragePage() {
  const matter = decodeURIComponent(useParams<{ matter: string }>().matter);
  const [d, setD] = useState<Coverage | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    getCoverage(matter)
      .then((r) => {
        setD(r);
        setOpen((o) => (o.size ? o : new Set(r.sections.slice(0, 1).map((s) => s.section))));
      })
      .catch((e) => setErr(String(e)));
  }, [matter]);
  useEffect(load, [load]);
  useLiveVersion(load);

  if (err) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--stop)" }}>{err}</main>;
  if (!d) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--text-3)" }}>Loading…</main>;

  const base = `/m/${encodeURIComponent(matter)}`;
  const t = d.totals;
  const toggle = (k: string) =>
    setOpen((o) => {
      const n = new Set(o);
      n.has(k) ? n.delete(k) : n.add(k);
      return n;
    });

  return (
    <main className="mx-auto w-full max-w-[1560px] px-10 py-10">
      <PageHeader
        crumbs={[{ label: matter, href: base }, { label: "Correlation" }]}
        title={d.outline}
        description="What the memo has to be able to say, and which prompts supply the evidence for each claim. Sections carry their playbook reference; assertions carry their citation."
        right={
          <span className="text-[11.5px]" style={{ color: "var(--text-3)" }}>
            outline v{d.outline_version} · {d.sections.length} sections
          </span>
        }
      />

      <div className="mb-9 grid grid-cols-2 gap-4 sm:grid-cols-5">
        <Stat label="Assertions" value={t.assertions} icon={BookOpen} />
        <Stat label="Sourced" value={t.nominally_covered} icon={CircleDashed} />
        <Stat label="Reliably covered" value={t.reliably_covered} tone={t.reliably_covered ? "ok" : undefined} icon={CircleCheck} />
        <Stat label="Attorney judgment" value={t.judgment_boundary} icon={Scale} />
        <Stat label="Extraction gaps" value={t.extraction_gap} tone={t.extraction_gap ? "stop" : "ok"} icon={TriangleAlert} />
      </div>

      {t.reliably_covered === 0 && (
        <p className="mb-6 rounded-lg border px-4 py-3 text-[12.5px]" style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text-2)" }}>
          Nothing reads <strong style={{ color: "var(--text)" }}>reliably covered</strong> because no
          prompt has been run against documents yet. Every sourced assertion stays{" "}
          <strong style={{ color: "var(--text)" }}>sourced</strong> until a run exists. That is the
          expected state, not a defect. <strong style={{ color: "var(--text)" }}>{t.extraction_gap} extraction gaps</strong>{" "}
          is the number that would mean a real hole in the schema.
        </p>
      )}

      <div className="grid gap-7 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-2.5">
          {d.sections.map((s) => {
            const isOpen = open.has(s.section);
            const counts = s.assertions.reduce<Record<string, number>>((a, x) => {
              a[x.status] = (a[x.status] ?? 0) + 1;
              return a;
            }, {});
            return (
              <section key={s.section} className="card overflow-hidden">
                <button onClick={() => toggle(s.section)} className="rowlink flex w-full items-center gap-3 px-5 py-3 text-left">
                  {isOpen ? <ChevronDown size={14} style={{ color: "var(--text-3)" }} /> : <ChevronRight size={14} style={{ color: "var(--text-3)" }} />}
                  <span className="min-w-0 flex-1 truncate font-medium">{s.section}</span>
                  <span className="mono shrink-0 text-[11.5px]" style={{ color: "var(--text-3)" }}>
                    {s.assertions.length}
                  </span>
                  {counts.extraction_gap > 0 && <Pill tone="stop">{counts.extraction_gap} gap</Pill>}
                </button>
                {isOpen && (
                  <div className="border-t">
                    {s.assertions.map((a, i) => (
                      <Assertion key={i} a={a} base={base} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>

        <aside className="self-start">
          <Panel title={`Prompts feeding no assertion · ${d.unsourced_columns.length}`} icon={Unplug} bodyClassName="max-h-[70vh] overflow-y-auto">
            <p className="border-b px-5 py-3 text-[12px]" style={{ color: "var(--text-3)" }}>
              Mostly routing and spine infrastructure, which correctly supports no claim of its
              own. The rest are candidates to retire or to wire up.
            </p>
            {d.unsourced_columns.map((c, i) => (
              <Link
                key={i}
                href={`${base}/t/${encodeURIComponent(c.table)}/c/${encodeURIComponent(c.column)}`}
                className="rowlink block border-b px-5 py-2.5 last:border-b-0"
              >
                <div className="text-[12.5px] font-medium">{c.column}</div>
                <div className="text-[11.5px]" style={{ color: "var(--text-3)" }}>
                  {c.table} · {c.role ?? "no role"}
                </div>
              </Link>
            ))}
          </Panel>
        </aside>
      </div>
    </main>
  );
}

function Assertion({ a, base }: { a: CoverageAssertion; base: string }) {
  const st = STATUS[a.status] ?? STATUS.nominally_covered;
  return (
    <div className="border-b px-5 py-3.5 last:border-b-0">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
        <span className="min-w-0 flex-1 text-[13px]">{a.assertion}</span>
        <span className="flex shrink-0 items-center gap-1.5">
          <Pill>{a.kind}</Pill>
          <span title={st.hint}>
            <Pill tone={st.tone}>{st.label}</Pill>
          </span>
        </span>
      </div>

      {a.note && (
        <p className="mt-1.5 text-[12px]" style={{ color: "var(--text-3)" }}>
          {a.note}
        </p>
      )}

      {a.sources.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {a.sources.map((s, i) => (
            <Link
              key={i}
              href={`${base}/t/${encodeURIComponent(s.table)}/c/${encodeURIComponent(s.column)}`}
              className="text-[11.5px] hover:underline"
              style={{ color: "var(--text-2)" }}
            >
              {s.column} <span style={{ color: "var(--text-3)" }}>· {s.table}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
