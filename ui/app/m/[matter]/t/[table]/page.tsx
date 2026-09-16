"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Term } from "@/components/Tip";
import { useLiveVersion } from "@/components/Live";
import {GoChevron, PageHeader, Panel, Pill, statusTone} from "@/components/ui";
import {
  BookOpen, ClipboardCheck, FileText, FlaskConical, Files, LayoutGrid, ListChecks, Network, Scale,
  CircleDashed, Variable,
} from "lucide-react";

const CAUSE_ICON: Record<string, React.ComponentType<{ size?: number }>> = {
  prompts: FileText,
  graph: Network,
  parameters: Variable,
  consistency: Scale,
  coverage: BookOpen,
  status: CircleDashed,
  evaluation: FlaskConical,
  coverage_dimensions: LayoutGrid,
  document_set: Files,
};
import { ModuleGraph } from "@/components/ModuleGraph";
import { getGraph, getTable, type TableDetail, type TableGraph } from "@/lib/api";

const CAUSE_LABEL: Record<string, string> = {
  prompts: "Prompt lint",
  graph: "Dependencies",
  parameters: "Parameters",
  consistency: "Consistency",
  coverage: "Supports the memo",
  status: "Lifecycle",
  evaluation: "Evaluation",
  coverage_dimensions: "Test coverage",
  document_set: "Document set",
};

export default function TablePage() {
  const p = useParams<{ matter: string; table: string }>();
  const matter = decodeURIComponent(p.matter);
  const table = decodeURIComponent(p.table);
  const [d, setD] = useState<TableDetail | null>(null);
  const [g, setG] = useState<TableGraph | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    getTable(matter, table).then(setD).catch((e) => setErr(String(e)));
    getGraph(matter, table).then(setG).catch(() => setG(null));
  }, [matter, table]);
  useEffect(load, [load]);
  useLiveVersion(load);

  if (err) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--stop)" }}>{err}</main>;
  if (!d) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--text-3)" }}>Loading…</main>;

  const base = `/m/${encodeURIComponent(matter)}`;
  const causes = Object.entries(d.readiness.by_cause ?? {}).filter(([, v]) => v.length > 0);

  return (
    <main className="mx-auto w-full max-w-[1560px] px-10 py-10">
      <PageHeader
        crumbs={[{ label: matter, href: base }, { label: d.table }]}
        title={d.table}
        description={
          d.review_unit ? (
            <>
              <span className="eyebrow mr-1.5"><Term k="review_unit">One row =</Term></span>
              {d.review_unit}
            </>
          ) : null
        }
        right={
          <>
            <Pill tone="accent">{d.column_count} prompts</Pill>
            {d.grouping_enabled && <Pill>grouped</Pill>}
            {d.readiness.total > 0 && <Pill tone="warn">{d.readiness.total} findings</Pill>}
          </>
        }
      />

      {g && g.edges.length > 0 && (
        <div className="mb-9">
          <div className="eyebrow mb-3 flex items-center gap-1.5">
            <Network size={12} strokeWidth={2.25} />
            <Term k="reference_graph">Reference graph</Term> · {g.edges.length} edges · {g.depth} levels
          </div>
          <ModuleGraph g={g} base={`${base}/t/${encodeURIComponent(d.table)}`} />
        </div>
      )}

      <div className="grid gap-7 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section>
          <Panel title="Prompts" icon={ListChecks}>
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b">
                  <th className="eyebrow mb-0 px-5 py-3 font-semibold">#</th>
                  <th className="eyebrow mb-0 px-5 py-3 font-semibold">Prompt</th>
                  <th className="eyebrow mb-0 px-5 py-3 font-semibold"><Term k="native_type">Type</Term></th>
                  <th className="eyebrow mb-0 px-5 py-3 font-semibold"><Term k="role">Role</Term></th>
                  <th className="eyebrow mb-0 px-5 py-3 font-semibold"><Term k="status">Status</Term></th>
                  <th className="eyebrow mb-0 px-5 py-3 text-right font-semibold">Ver</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {d.columns.map((c) => (
                  <tr key={c.column_id} className="rowlink border-b last:border-b-0">
                    <td className="mono px-5 py-3.5 align-top text-[11.5px]" style={{ color: "var(--text-3)" }}>{c.position}</td>
                    <td className="px-5 py-3.5 align-top">
                      <Link
                        href={`${base}/t/${encodeURIComponent(d.table)}/c/${encodeURIComponent(c.name)}`}
                        className="font-medium hover:underline"
                      >
                        {c.name}
                      </Link>
                      {c.purpose && (
                        <div className="mt-0.5 line-clamp-1 max-w-[440px] text-[12.5px]" style={{ color: "var(--text-3)" }}>
                          {c.purpose}
                        </div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 align-top"><Term k={c.native_type} underline={false}><Pill>{c.native_type}</Pill></Term></td>
                    <td className="whitespace-nowrap px-5 py-3.5 align-top text-[12.5px]" style={{ color: "var(--text-2)" }}>
                      {c.role ? <Term k={c.role}>{c.role}</Term> : "–"}
                    </td>
                    <td className="px-5 py-3.5 align-top"><Term k={c.status} underline={false}><Pill tone={statusTone(c.status)}>{c.status}</Pill></Term></td>
                    <td className="mono px-5 py-3.5 text-right align-top text-[12.5px]" style={{ color: "var(--text-2)" }}>{c.version}</td>
                    <td className="w-8 pr-3 align-middle"><GoChevron /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </section>

        <aside>
          <Panel title={`Readiness · ${d.readiness.total}`} icon={ClipboardCheck} bodyClassName="max-h-[70vh] overflow-y-auto">
            {causes.length === 0 && (
              <div className="px-4 py-3 text-[12.5px]" style={{ color: "var(--text-3)" }}>Nothing outstanding.</div>
            )}
            {causes.map(([cause, findings]) => (
              <div key={cause} className="border-b last:border-b-0">
                <div className="flex items-center justify-between px-5 py-2.5" style={{ background: "var(--surface-2)" }}>
                  <span className="eyebrow mb-0 flex items-center gap-1.5">
                    {(() => { const I = CAUSE_ICON[cause] ?? FileText; return <I size={12} />; })()}
                    {CAUSE_LABEL[cause] ?? cause}
                  </span>
                  <span className="mono text-[11.5px]" style={{ color: "var(--text-3)" }}>{findings.length}</span>
                </div>
                {findings.slice(0, 8).map((f, i) => (
                  <div key={i} className="border-t px-5 py-3 text-[12.5px]">
                    <div className="mono mb-0.5 text-[10.5px]" style={{ color: "var(--text-3)" }}>
                      <Term k={f.code}>{f.code}</Term>
                    </div>
                    <div style={{ color: "var(--text-2)" }}>{f.observation}</div>
                  </div>
                ))}
                {findings.length > 8 && (
                  <div className="border-t px-5 py-2 text-[11.5px]" style={{ color: "var(--text-3)" }}>
                    +{findings.length - 8} more
                  </div>
                )}
              </div>
            ))}
          </Panel>
        </aside>
      </div>
    </main>
  );
}
