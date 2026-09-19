"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, CircleSlash, Layers, ListChecks, ScrollText } from "lucide-react";
import { Crumbs, Eyebrow, PageHeader, Panel, Pill, Stat } from "@/components/ui";
import { getPlaybook, type PlaybookDetail, type PlaybookRule } from "@/lib/api";

/** Standard, acceptable, unacceptable. A rule with no unacceptable position has no defined
 *  treatment for anything past its last fallback, and across a playbook that reads as a wall
 *  of open right-hand ends, which is the thing worth seeing before any individual finding. */
function Ladder({ r }: { r: PlaybookRule }) {
  const steps = [
    { label: "standard", on: !!r.standard, tone: "var(--accent)" },
    { label: `acceptable · ${r.acceptable.length}`, on: r.acceptable.length > 0, tone: "var(--ok)" },
    { label: "unacceptable", on: r.unacceptable.length > 0, tone: "var(--stop)" },
  ];
  return (
    <span className="flex items-stretch gap-[3px]">
      {steps.map((s) => (
        <span
          key={s.label}
          title={s.on ? s.label : `no ${s.label.split(" ")[0]} position`}
          className="h-[7px] w-12 rounded-sm"
          style={{
            background: s.on ? s.tone : "transparent",
            border: s.on ? "none" : "1px dashed var(--border-2)",
            opacity: s.on ? 0.85 : 1,
          }}
        />
      ))}
    </span>
  );
}

export default function PlaybookPage() {
  const file = decodeURIComponent(useParams<{ file: string }>().file);
  const [d, setD] = useState<PlaybookDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    getPlaybook(file).then(setD).catch((e) => setErr(String(e)));
  }, [file]);

  if (err)
    return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--stop)" }}>{err}</main>;
  if (!d)
    return <main className="mx-auto w-full max-w-[1560px] px-10 py-10" style={{ color: "var(--text-3)" }}>Loading…</main>;

  const c = d.counts;
  const byCode = new Map<string, number>();
  for (const f of d.findings) byCode.set(f.code, (byCode.get(f.code) ?? 0) + 1);
  const sel = d.rules.find((r) => r.name === open) ?? null;

  return (
    <main className="mx-auto w-full max-w-[1560px] px-10 py-10">
      <Crumbs items={[{ label: "Playbooks", href: "/playbooks" }, { label: d.name }]} />
      <PageHeader
        title={d.name}
        description="Five fields per rule are the platform's whole schema. Identity, dependencies, precedence, absence remediation, exhaustion and provenance live inside Guidance by convention, where nothing can validate them. This reads both."
        right={<Pill tone={c.findings ? "warn" : "ok"}>{c.findings} findings</Pill>}
      />

      <div className="mb-7 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Rules" value={c.rules} icon={ListChecks} />
        <Stat label="Required" value={c.required} icon={ScrollText} />
        <Stat label="With acceptable" value={c.with_acceptable} tone={c.with_acceptable < c.rules ? "warn" : undefined} />
        <Stat label="With unacceptable" value={c.with_unacceptable} tone={c.with_unacceptable < c.rules ? "warn" : undefined} />
        <Stat label="With a rule ID" value={c.with_rule_id} tone={c.with_rule_id === 0 ? "warn" : undefined} />
        <Stat label="With dependencies" value={c.with_dependencies} tone={c.with_dependencies === 0 ? "warn" : undefined} />
      </div>

      {c.with_rule_id === 0 && (
        <div className="card mb-7 px-5 py-3.5 text-[12.5px]" style={{ color: "var(--text-2)" }}>
          No rule carries an identifier, a dependency or a source. The authoring conventions that
          hold those live inside Guidance, and this playbook predates them, so nothing here records
          how these rules relate to each other: not because the relationships are absent, but
          because there is nowhere they have been written down.
        </div>
      )}

      <div className="grid grid-cols-1 gap-7 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Panel
          title="Rules"
          icon={Layers}
          right={
            <span className="flex items-center gap-3 text-[11px]" style={{ color: "var(--text-3)" }}>
              <span className="flex items-center gap-1.5"><i className="h-[7px] w-5 rounded-sm" style={{ background: "var(--accent)", opacity: 0.85 }} /> standard</span>
              <span className="flex items-center gap-1.5"><i className="h-[7px] w-5 rounded-sm" style={{ background: "var(--ok)", opacity: 0.85 }} /> acceptable</span>
              <span className="flex items-center gap-1.5"><i className="h-[7px] w-5 rounded-sm" style={{ background: "var(--stop)", opacity: 0.85 }} /> unacceptable</span>
            </span>
          }
        >
          {d.rules.map((r) => (
            <button
              key={r.name}
              onClick={() => setOpen(open === r.name ? null : r.name)}
              className="rowlink flex w-full items-center gap-4 border-b px-5 py-2.5 text-left last:border-b-0"
              data-on={open === r.name}
            >
              <span className="mono w-6 shrink-0 text-[11px]" style={{ color: "var(--text-3)" }}>{r.position}</span>
              <span className="min-w-0 flex-1 truncate text-[12.5px]">{r.name}</span>
              {r.required && <Pill>required</Pill>}
              <Ladder r={r} />
              <span
                className="mono w-7 shrink-0 text-right text-[11px]"
                style={{ color: r.findings.length ? "var(--warn)" : "var(--text-3)" }}
              >
                {r.findings.length || ""}
              </span>
            </button>
          ))}
        </Panel>

        <div className="space-y-7">
          <Panel title={`Findings · ${d.findings.length}`} icon={AlertTriangle}>
            {[...byCode.entries()]
              .sort((a, b) => b[1] - a[1])
              .map(([code, n]) => (
                <div key={code} className="flex items-baseline gap-3 border-b px-5 py-2.5 last:border-b-0">
                  <span className="mono w-7 shrink-0 text-right text-[11.5px]" style={{ color: "var(--warn)" }}>{n}</span>
                  <span className="mono min-w-0 flex-1 break-all text-[11px]" style={{ color: "var(--text-2)" }}>{code}</span>
                </div>
              ))}
          </Panel>

          {sel && (
            <Panel title={sel.name} icon={ScrollText}>
              <div className="space-y-3 px-5 py-3.5 text-[12.5px]">
                <Field label="Standard position" body={sel.standard} />
                <Field label={`Acceptable · ${sel.acceptable.length}`} items={sel.acceptable} />
                <Field label={`Unacceptable · ${sel.unacceptable.length}`} items={sel.unacceptable} />
                {sel.workflow.length > 0 && <Field label="Workflow actions" items={sel.workflow} />}
                <Field label="Guidance" body={sel.guidance} />
              </div>
              {sel.findings.length > 0 && (
                <div className="border-t">
                  <Eyebrow icon={CircleSlash} className="px-5 pt-3">On this rule</Eyebrow>
                  {sel.findings.map((f, i) => (
                    <div key={i} className="px-5 pb-2.5 pt-1">
                      <div className="mono text-[10.5px]" style={{ color: "var(--warn)" }}>{f.code}</div>
                      <div className="text-[12.5px]" style={{ color: "var(--text-2)" }}>{f.observation}</div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          )}
          {!sel && (
            <p className="px-1 text-[12.5px]" style={{ color: "var(--text-3)" }}>
              Select a rule to read its five fields and what the checks found in it.
            </p>
          )}
        </div>
      </div>
    </main>
  );
}

function Field({ label, body, items }: { label: string; body?: string; items?: string[] }) {
  const empty = !body && !(items && items.length);
  return (
    <div>
      <div className="eyebrow mb-1">{label}</div>
      {empty ? (
        <div className="text-[12.5px]" style={{ color: "var(--text-3)" }}>not stated</div>
      ) : items ? (
        <ul className="space-y-1">
          {items.map((x, i) => (
            <li key={i} style={{ color: "var(--text-2)" }}>{x}</li>
          ))}
        </ul>
      ) : (
        <div className="whitespace-pre-wrap" style={{ color: "var(--text-2)" }}>{body}</div>
      )}
    </div>
  );
}
