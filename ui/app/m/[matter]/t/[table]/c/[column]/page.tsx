"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Term } from "@/components/Tip";
import { useLiveVersion } from "@/components/Live";
import { PageHeader, Panel, Pill, statusTone } from "@/components/ui";
import {
  ArrowDownLeft, ArrowUpRight, BookOpen, FileText, FlaskConical, History, List, Undo2, Variable,
} from "lucide-react";
import { getColumn, type ColumnDetail } from "@/lib/api";

export default function ColumnPage() {
  const p = useParams<{ matter: string; table: string; column: string }>();
  const matter = decodeURIComponent(p.matter);
  const table = decodeURIComponent(p.table);
  const column = decodeURIComponent(p.column);
  const [d, setD] = useState<ColumnDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showVersion, setShowVersion] = useState<string | null>(null);

  const load = useCallback(() => {
    getColumn(matter, table, column).then(setD).catch((e) => setErr(String(e)));
  }, [matter, table, column]);
  useEffect(load, [load]);
  useLiveVersion(load);

  if (err) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--stop)" }}>{err}</main>;
  if (!d) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--text-3)" }}>Loading…</main>;

  const base = `/m/${encodeURIComponent(matter)}`;
  const shown = d.history.find((h) => h.version === showVersion) ?? null;
  const text = shown ? shown.text : d.prompt_text;

  return (
    <main className="mx-auto w-full max-w-[1560px] px-10 py-10">
      <PageHeader
        crumbs={[
          { label: matter, href: base },
          { label: table, href: `${base}/t/${encodeURIComponent(table)}` },
          { label: d.name },
        ]}
        title={d.name}
        description={d.purpose}
        right={
          <>
            <Term k={d.native_type} underline={false}><Pill tone="accent">{d.native_type}</Pill></Term>
            <Term k={d.status} underline={false}><Pill tone={statusTone(d.status)}>{d.status}</Pill></Term>
            {d.role && <Term k={d.role} underline={false}><Pill>{d.role}</Pill></Term>}
            <Term
              k={d.staleness.state === "direct" ? "stale_direct" : d.staleness.state === "transitive" ? "stale_transitive" : d.staleness.state}
              underline={false}
            >
              <Pill tone={d.staleness.state === "current" ? "ok" : d.staleness.state === "never_run" ? "neutral" : "warn"}>
                {d.staleness.state.replace("_", " ")}
              </Pill>
            </Term>
            <span className="mono text-[11.5px]" style={{ color: "var(--text-3)" }}>
              {d.version} · {d.char_count.toLocaleString()} chars
            </span>
          </>
        }
      />

      <div className="grid gap-7 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section>
          <Panel
            title={`Prompt ${shown ? `· ${shown.version}` : "· current"}`}
            icon={FileText}
            right={
              shown && (
                <button
                  onClick={() => setShowVersion(null)}
                  className="flex items-center gap-1 text-[12.5px] hover:underline"
                  style={{ color: "var(--accent)" }}
                >
                  <Undo2 size={12} />
                  back to current
                </button>
              )
            }
          >
            <pre
              className="mono overflow-x-auto px-5 py-4 text-[12.5px] leading-[1.75] whitespace-pre-wrap"
              style={{ color: "var(--text)" }}
            >
              {text}
            </pre>
          </Panel>

          {d.configured_options && d.configured_options.length > 0 && (
            <>
              <div className="mt-8">
                <Panel title="Configured options" icon={List} bodyClassName="flex flex-wrap gap-1.5 px-5 py-3.5">
                  {d.configured_options.map((o) => <Pill key={o}>{o}</Pill>)}
                </Panel>
              </div>
            </>
          )}

          <div className="mt-8">
          <Panel title={`Version history · ${d.history.length}`} icon={History}>
            {d.history.map((h) => (
              <button
                key={h.version}
                onClick={() => setShowVersion(h.is_current ? null : h.version)}
                className="rowlink flex w-full items-baseline justify-between gap-3 border-b px-5 py-2.5 text-left last:border-b-0"
              >
                <span className="flex items-baseline gap-2">
                  <span className="mono text-[12.5px] font-medium">{h.version}</span>
                  {h.is_current && <Pill tone="ok">current</Pill>}
                  <span className="text-[12.5px]" style={{ color: "var(--text-2)" }}>
                    {h.change_note ?? "no note"}
                  </span>
                </span>
                <span className="mono shrink-0 text-[11.5px]" style={{ color: "var(--text-3)" }}>
                  {h.char_count.toLocaleString()}
                </span>
              </button>
            ))}
          </Panel>
          </div>
        </section>

        <aside className="space-y-6">
          <div>
            <Panel title={`Depends on · ${d.upstream.length}`} icon={ArrowDownLeft}>
              {d.upstream.length === 0 && <Empty>Nothing upstream.</Empty>}
              {d.upstream.map((u, i) => (
                <DepRow key={i} base={base} dep={u} />
              ))}
            </Panel>
          </div>
          <div>
            <Panel title={`Feeds · ${d.downstream.length}`} icon={ArrowUpRight}>
              {d.downstream.length === 0 && <Empty>Nothing downstream.</Empty>}
              {d.downstream.map((u, i) => (
                <DepRow key={i} base={base} dep={u} />
              ))}
            </Panel>
          </div>
          {d.consumes_parameters.length > 0 && (
            <div>
              <Panel title="Parameters used" icon={Variable}>
                {d.consumes_parameters.map((p, i) => (
                  <div key={i} className="border-b px-5 py-2.5 last:border-b-0 text-[12.5px]">
                    <div className="font-medium">{p.name}</div>
                    <div style={{ color: "var(--text-3)" }}>{p.value ?? "unresolved"}</div>
                  </div>
                ))}
              </Panel>
            </div>
          )}
          <div>
            <Panel
              title={`Supports the memo · ${d.memo_assertions?.length ?? 0}`}
              icon={BookOpen}
            >
              {!d.memo_assertions?.length ? (
                <Empty>Feeds no memo assertion.</Empty>
              ) : (
                d.memo_assertions.map((a, i) => (
                  <div key={i} className="border-b px-5 py-2.5 last:border-b-0">
                    <div className="text-[12.5px]">{a.text}</div>
                    <div className="mt-0.5 text-[11.5px]" style={{ color: "var(--text-3)" }}>
                      {a.section} · {a.kind}
                    </div>
                  </div>
                ))
              )}
            </Panel>
          </div>
          <div>
            <Panel title="Evaluation" icon={FlaskConical} bodyClassName="px-5 py-3.5 text-[12.5px]">
              {d.evaluation.runs === 0 ? (
                <span style={{ color: "var(--text-3)" }}>Never run.</span>
              ) : (
                <div className="space-y-1">
                  <Row k="Runs" v={d.evaluation.runs} />
                  <Row k="Documents tested" v={d.evaluation.documents_tested} />
                  <Row k="Open failures" v={d.evaluation.open_failures} />
                </div>
              )}
            </Panel>
          </div>
        </aside>
      </div>
    </main>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-3 text-[12.5px]" style={{ color: "var(--text-3)" }}>{children}</div>;
}
function Row({ k, v }: { k: string; v: number }) {
  return (
    <div className="flex justify-between">
      <span style={{ color: "var(--text-2)" }}>{k}</span>
      <span className="mono">{v}</span>
    </div>
  );
}
function DepRow({ base, dep }: { base: string; dep: { table: string; column: string; kind: string } }) {
  return (
    <Link
      href={`${base}/t/${encodeURIComponent(dep.table)}/c/${encodeURIComponent(dep.column)}`}
      className="rowlink block border-b px-5 py-2.5 last:border-b-0"
    >
      <div className="text-[12.5px] font-medium">{dep.column}</div>
      <div className="text-[11.5px]" style={{ color: "var(--text-3)" }}>
        {dep.table} · {dep.kind.replace(/_/g, " ")}
      </div>
    </Link>
  );
}
