"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, CircleDashed, FileQuestion, Layers, ScrollText, Shuffle, Table2 } from "lucide-react";
import { useLiveVersion } from "@/components/Live";
import { PageHeader, Panel, Pill, Stat } from "@/components/ui";
import { getRegister, type ReqPart, type Register } from "@/lib/api";

/** `external` is a deliberate boundary, not a defect: a requirement no review table can serve,
 *  recorded with its reason. It must not read as red, for the same reason a judgment boundary
 *  must not. `unassessed` is the one that means work outstanding. */
const DISPOSITION: Record<string, { label: string; tone: "ok" | "accent" | "neutral" | "warn"; hint: string }> = {
  served: { label: "served", tone: "ok", hint: "a review table answers this" },
  synthesis: { label: "synthesis", tone: "accent", hint: "needs cross-document work over table output" },
  external: { label: "external", tone: "neutral", hint: "no review table can serve this, and here is why" },
  unassessed: { label: "unassessed", tone: "warn", hint: "no disposition decided yet" },
};

export default function RequirementsPage() {
  const matter = decodeURIComponent(useParams<{ matter: string }>().matter);
  const [d, setD] = useState<Register | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    getRegister(matter).then(setD).catch((e) => setErr(String(e)));
  }, [matter]);
  useEffect(load, [load]);
  useLiveVersion(load);

  if (err) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--stop)" }}>{err}</main>;
  if (!d) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--text-3)" }}>Loading…</main>;

  const base = `/m/${encodeURIComponent(matter)}`;
  const c = d.counts;
  const src = d.sources[0];

  return (
    <main className="mx-auto w-full max-w-[1560px] px-10 py-10">
      <PageHeader
        crumbs={[{ label: matter, href: base }, { label: "Requirements" }]}
        title={src ? src.source : "Requirements"}
        description={
          src
            ? "The external specification this suite was built to satisfy, and what each item resolved to. An item marked external is one no review table can serve, recorded with the reason: a deliberate boundary, not a gap."
            : "No requirement source is stored, so nothing states what this suite was built to satisfy."
        }
        right={src?.citation ? <span className="text-[11.5px]" style={{ color: "var(--text-3)" }}>{src.citation}</span> : undefined}
      />

      {!src ? (
        <p className="rounded-lg border px-5 py-4 text-[13px]" style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text-2)" }}>
          Record one with <code className="mono">requirements_ingest</code>. Until then, coverage
          can only check the memo this team wrote against the columns this team wrote.
        </p>
      ) : (
        <>
          <div className="mb-9 grid grid-cols-2 gap-4 sm:grid-cols-5">
            <Stat label="Requirements" value={c.requirements} icon={ScrollText} />
            <Stat label="Served by a table" value={c.served} tone={c.served ? "ok" : undefined} icon={Table2} />
            <Stat label="Cross-document" value={c.synthesis} icon={Shuffle} />
            <Stat label="External" value={c.external} icon={FileQuestion} />
            <Stat label="Unassessed" value={c.unassessed} tone={c.unassessed ? "warn" : undefined} icon={CircleDashed} />
          </div>

          <div className="grid gap-7 xl:grid-cols-[minmax(0,1fr)_300px]">
            <Panel title={`Requirements · ${src.requirements.length}`} icon={ScrollText}>
              {src.requirements.map((r) => (
                <div key={r.ref} className="border-b px-5 py-3.5 last:border-b-0">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="mono shrink-0 text-[12px]" style={{ color: "var(--text-3)" }}>{r.ref}</span>
                    <span className="min-w-0 flex-1 text-[13px] font-medium">{r.title}</span>
                  </div>
                  {r.parts.map((p, i) => (
                    <Part key={i} p={p} base={base} />
                  ))}
                </div>
              ))}
            </Panel>

            <aside className="self-start">
              <Panel title={`Tables answering nothing · ${d.tables_answering_nothing.length}`} icon={Layers}>
                <p className="border-b px-5 py-3 text-[12px]" style={{ color: "var(--text-3)" }}>
                  No requirement in this source names them. That can be correct: a table may be
                  justified against a different part of the specification.
                </p>
                {d.tables_answering_nothing.map((t) => (
                  <Link
                    key={t.table}
                    href={`${base}/t/${encodeURIComponent(t.table)}`}
                    className="rowlink block border-b px-5 py-2.5 text-[12.5px] last:border-b-0"
                  >
                    {t.table}
                  </Link>
                ))}
              </Panel>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

function Part({ p, base }: { p: ReqPart; base: string }) {
  const d = DISPOSITION[p.disposition] ?? DISPOSITION.unassessed;
  return (
    <div className="mt-2 flex flex-wrap items-start gap-x-3 gap-y-1.5">
      <span className="flex shrink-0 items-center gap-1.5">
        {p.label && (
          <span className="text-[11.5px] font-medium" style={{ color: "var(--text-3)" }}>{p.label}</span>
        )}
        <span title={d.hint}>
          <Pill tone={d.tone}>{d.label}</Pill>
        </span>
      </span>
      <span className="min-w-0 flex-1">
        {p.reason && (
          <span className="block text-[12px]" style={{ color: "var(--text-3)" }}>{p.reason}</span>
        )}
        {p.links.length > 0 && (
          <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
            {p.links.map((l, i) => (
              <span key={i} className="flex items-center gap-1 text-[11.5px]">
                <span style={{ color: "var(--text-3)" }}>{l.kind.replace("_", " ")}</span>
                {l.table ? (
                  <Link href={`${base}/t/${encodeURIComponent(l.table)}`} className="hover:underline" style={{ color: "var(--text-2)" }}>
                    {l.table}
                  </Link>
                ) : (
                  <Link href={`${base}/coverage`} className="flex items-center gap-0.5 hover:underline" style={{ color: "var(--text-2)" }}>
                    {l.section} <ArrowUpRight size={10} />
                  </Link>
                )}
              </span>
            ))}
          </span>
        )}
      </span>
    </div>
  );
}
