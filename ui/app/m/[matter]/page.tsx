"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { LiveDot, useLiveVersion } from "@/components/Live";
import {GoChevron, PageHeader, Panel, Stat} from "@/components/ui";
import {
  Activity, AlertTriangle, CircleCheck, CircleDashed, Clock, Layers, ListChecks, Variable,
  Plus, Pencil, GitCommitVertical, Circle,
} from "lucide-react";

const ACTION_ICON: Record<string, React.ComponentType<{ size?: number }>> = {
  create: Plus,
  set: Pencil,
  version: GitCommitVertical,
};
import { getActivity, getMatter, type ActivityEvent, type Matter } from "@/lib/api";

function ago(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export default function MatterPage() {
  const matter = decodeURIComponent(useParams<{ matter: string }>().matter);
  const [m, setM] = useState<Matter | null>(null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    getMatter(matter).then(setM).catch((e) => setErr(String(e)));
    getActivity(matter).then((r) => { setEvents(r.events); setTotal(r.total); }).catch(() => {});
  }, [matter]);
  useEffect(load, [load]);
  const { online } = useLiveVersion(load);

  if (err)
    return (
      <main className="mx-auto w-full max-w-[1560px] px-10 py-10">
        <p style={{ color: "var(--stop)" }}>{err}</p>
        <p className="mt-1" style={{ color: "var(--text-2)" }}>
          Is the read API running? <code className="mono">prompt-graph-api</code>
        </p>
      </main>
    );
  if (!m) return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--text-3)" }}>Loading…</main>;

  const st = m.staleness;
  const stale = st.direct + st.transitive;

  return (
    <main className="mx-auto w-full max-w-[1560px] px-10 py-10">
      <PageHeader
        title={m.matter}
        description={m.objective}
        right={<LiveDot online={online} />}
      />

      <div className="mb-9 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Modules" value={m.table_count} icon={Layers} />
        <Stat label="Rules" value={m.column_count} icon={ListChecks} />
        <Stat termKey="never_run" label="Never run" value={st.never_run} tone={st.never_run ? "warn" : undefined} icon={CircleDashed} />
        <Stat termKey="current" label="Current" value={st.current} tone={st.current ? "ok" : undefined} icon={CircleCheck} />
        <Stat termKey="staleness" label="Stale" value={stale} tone={stale ? "warn" : undefined} icon={Clock} />
        <Stat termKey="open_failures" label="Open failures" value={m.open_failures} tone={m.open_failures ? "stop" : undefined} icon={AlertTriangle} />
      </div>

      <div className="grid gap-7 xl:grid-cols-[minmax(0,1fr)_310px]">
        <section>
          <Panel title="Modules" icon={Layers}>
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b">
                  <th className="eyebrow mb-0 px-5 py-3 font-semibold">Module</th>
                  <th className="eyebrow mb-0 px-5 py-3 font-semibold">Review unit</th>
                  <th className="eyebrow mb-0 px-4 py-2.5 text-right font-semibold">Rules</th>
                  <th className="eyebrow mb-0 px-5 py-3 font-semibold">State</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {m.tables.map((t) => {
                  const s = t.staleness.direct + t.staleness.transitive;
                  return (
                    <tr key={t.table} className="rowlink border-b last:border-b-0">
                      <td className="px-5 py-3.5 align-top">
                        <Link
                          href={`/m/${encodeURIComponent(m.matter)}/t/${encodeURIComponent(t.table)}`}
                          className="font-medium hover:underline"
                        >
                          {t.table}
                        </Link>
                      </td>
                      <td className="max-w-[440px] px-5 py-3.5 align-top text-[12.5px]" style={{ color: "var(--text-2)" }}>
                        <span className="line-clamp-2">{t.review_unit ?? "not stated"}</span>
                      </td>
                      <td className="mono px-5 py-3.5 text-right align-top">{t.columns}</td>
                      <td className="whitespace-nowrap px-5 py-3.5 align-top text-[12.5px]">
                        {t.last_run ? (
                          s ? <span style={{ color: "var(--warn)" }}>{s} stale</span>
                            : <span style={{ color: "var(--ok)" }}>current</span>
                        ) : (
                          <span style={{ color: "var(--text-3)" }}>never run</span>
                        )}
                      </td>
                      <td className="w-8 pr-3 align-middle"><GoChevron /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>

          {m.parameters.length > 0 && (
            <>
              <div className="mt-7"><Panel title="Shared parameters" icon={Variable}>
                {m.parameters.map((p) => (
                  <div key={p.name} className="flex items-baseline justify-between gap-3 border-b px-5 py-2.5 last:border-b-0">
                    <span className="font-medium">{p.name}</span>
                    <span className="truncate text-[12.5px]" style={{ color: "var(--text-2)" }}>{p.value ?? "unresolved"}</span>
                    <span className="mono shrink-0 text-[11.5px]" style={{ color: "var(--text-3)" }}>{p.consumer_count} consumers</span>
                  </div>
                ))}
              </Panel></div>
            </>
          )}
        </section>

        <aside>
          <Panel title={`Activity · ${total}`} icon={Activity} bodyClassName="max-h-[68vh] overflow-y-auto">
            {events.map((e, i) => (
              <div key={e.id} className="border-b px-5 py-2.5 last:border-b-0">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="flex min-w-0 items-baseline gap-1.5 text-[12.5px]">
                    {(() => {
                      const I = ACTION_ICON[e.action] ?? Circle;
                      return <span className="shrink-0 translate-y-[2px]" style={{ color: "var(--text-3)" }}><I size={11} /></span>;
                    })()}
                    <span className="truncate">
                      <span style={{ color: "var(--text-3)" }}>{e.action} </span>
                      <span className="font-medium">{e.entity_name ?? e.entity_type}</span>
                    </span>
                  </span>
                  <span className="mono shrink-0 text-[11px]" style={{ color: "var(--text-3)" }}>{ago(e.at)}</span>
                </div>
                {e.actor && e.actor !== events[i - 1]?.actor && (
                  <div className="mt-0.5 text-[11px]" style={{ color: "var(--text-3)" }}>{e.actor}</div>
                )}
              </div>
            ))}
          </Panel>
        </aside>
      </div>
    </main>
  );
}
