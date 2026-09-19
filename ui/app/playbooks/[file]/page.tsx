"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  AlertTriangle, ChevronDown, ChevronRight, FileText, Layers, ListChecks, ScrollText,
} from "lucide-react";
import { Crumbs, Eyebrow, PageHeader, Panel, Pill, Stat } from "@/components/ui";
import { getPlaybook, type Deviation, type PlaybookDetail, type PlaybookRule } from "@/lib/api";

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

/** The five fields, verbatim. Legal prose needs the width, so this renders inside the row
 *  rather than in a sidebar: the point is to read what the rule actually says. */
function RuleBody({ r }: { r: PlaybookRule }) {
  const conventions = [
    r.rule_id && ["Rule ID", r.rule_id],
    r.depends_on.length > 0 && [
      "Depends on",
      r.depends_on.map((d) => `${d.ref}${d.reason ? ` (${d.reason})` : ""}`).join(" · "),
    ],
    r.precedence && ["Precedence", r.precedence],
    r.on_exhaustion && ["On exhaustion", r.on_exhaustion],
    r.source && ["Source", r.source + (r.reviewed ? ` · reviewed ${r.reviewed}` : "")],
  ].filter(Boolean) as [string, string][];

  return (
    <div className="border-t px-5 pb-5 pt-4" style={{ background: "var(--bg-2)" }}>
      <div className="grid grid-cols-1 gap-x-10 gap-y-5 lg:grid-cols-2">
        <Field label="Standard position" body={r.standard} />
        <Field label={`Acceptable deviations · ${r.acceptable.length}`} entries={r.acceptable} />
        <Field label={`Unacceptable deviations · ${r.unacceptable.length}`} entries={r.unacceptable} />
        <Field label="Guidance" body={r.guidance} />
        {r.workflow.length > 0 && <Field label="Workflow actions" items={r.workflow} />}
      </div>

      {conventions.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-x-6 gap-y-1.5 border-t pt-3">
          {conventions.map(([k, v]) => (
            <span key={k} className="text-[12px]">
              <span className="eyebrow mb-0 mr-1.5 inline">{k}</span>
              <span className="mono" style={{ color: "var(--text-2)" }}>{v}</span>
            </span>
          ))}
        </div>
      )}

      {r.findings.length > 0 && (
        <div className="mt-5 border-t pt-3">
          <Eyebrow icon={AlertTriangle}>Findings on this rule · {r.findings.length}</Eyebrow>
          <div className="mt-2 space-y-2">
            {r.findings.map((f, i) => (
              <div key={i} className="text-[12.5px]">
                <span className="mono mr-2 text-[10.5px]" style={{ color: "var(--warn)" }}>{f.code}</span>
                <span style={{ color: "var(--text-2)" }}>{f.observation}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  body,
  items,
  entries,
}: {
  label: string;
  body?: string;
  items?: string[];
  entries?: Deviation[];
}) {
  const empty = !body && !(items && items.length) && !(entries && entries.length);
  return (
    <div className="min-w-0">
      <div className="eyebrow mb-1.5">{label}</div>
      {empty ? (
        <div className="text-[12.5px] italic" style={{ color: "var(--text-3)" }}>not stated</div>
      ) : entries ? (
        // the title is what a reader scans; the body is why
        <ul className="space-y-2.5">
          {entries.map((e, i) => (
            <li key={i} className="text-[12.5px] leading-[1.6]">
              {e.label && <span className="block font-medium">{e.label}</span>}
              <span style={{ color: "var(--text-2)" }}>{e.body}</span>
            </li>
          ))}
        </ul>
      ) : items ? (
        <ul className="space-y-2">
          {items.map((x, i) => (
            <li key={i} className="text-[12.5px] leading-[1.6]" style={{ color: "var(--text-2)" }}>{x}</li>
          ))}
        </ul>
      ) : (
        <div
          className="whitespace-pre-wrap text-[12.5px] leading-[1.6]"
          style={{ color: "var(--text-2)" }}
        >
          {body}
        </div>
      )}
    </div>
  );
}

export default function PlaybookPage() {
  const file = decodeURIComponent(useParams<{ file: string }>().file);
  const [d, setD] = useState<PlaybookDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [preambleOpen, setPreambleOpen] = useState(false);

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
  const toggle = (n: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (!next.delete(n)) next.add(n);
      return next;
    });

  return (
    <main className="mx-auto w-full max-w-[1560px] px-10 py-10">
      <Crumbs items={[{ label: "Playbooks", href: "/playbooks" }, { label: d.name }]} />
      <PageHeader
        title={d.name}
        description="Five fields per rule are the platform's whole schema. Identity, dependencies, precedence, absence remediation, exhaustion and provenance live inside Guidance by convention, where nothing can validate them. This reads both."
        right={
          <span className="flex items-center gap-2">
            <button className="btn" onClick={() => setOpen(open.size ? new Set() : new Set(d.rules.map((r) => r.name)))}>
              {open.size ? "Collapse all" : "Expand all"}
            </button>
            <Pill tone={c.findings ? "warn" : "ok"}>{c.findings} findings</Pill>
          </span>
        }
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

      <div className="grid grid-cols-1 gap-7 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-7">
          {d.preamble && (
            <Panel title="AI Guidance (preamble)" icon={FileText}>
              <button
                onClick={() => setPreambleOpen((o) => !o)}
                className="rowlink flex w-full items-center gap-2 px-5 py-2.5 text-left text-[12.5px]"
              >
                {preambleOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <span style={{ color: "var(--text-2)" }}>
                  {preambleOpen ? "Hide" : "Show"} the document-level guidance every rule inherits
                </span>
              </button>
              {preambleOpen && (
                <div
                  className="whitespace-pre-wrap border-t px-5 py-4 text-[12.5px] leading-[1.6]"
                  style={{ color: "var(--text-2)", background: "var(--bg-2)" }}
                >
                  {d.preamble}
                </div>
              )}
            </Panel>
          )}

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
            {d.rules.map((r) => {
              const isOpen = open.has(r.name);
              return (
                <div key={r.name} className="border-b last:border-b-0">
                  <button
                    onClick={() => toggle(r.name)}
                    className="rowlink flex w-full items-center gap-3 px-5 py-2.5 text-left"
                    data-on={isOpen}
                  >
                    <span className="shrink-0" style={{ color: "var(--text-3)" }}>
                      {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    </span>
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
                  {isOpen && <RuleBody r={r} />}
                </div>
              );
            })}
          </Panel>
        </div>

        <Panel title={`Findings · ${d.findings.length}`} icon={AlertTriangle} className="self-start">
          {[...byCode.entries()]
            .sort((a, b) => b[1] - a[1])
            .map(([code, n]) => (
              <div key={code} className="flex items-baseline gap-3 border-b px-5 py-2.5 last:border-b-0">
                <span className="mono w-7 shrink-0 text-right text-[11.5px]" style={{ color: "var(--warn)" }}>{n}</span>
                <span className="mono min-w-0 flex-1 break-all text-[11px]" style={{ color: "var(--text-2)" }}>{code}</span>
              </div>
            ))}
        </Panel>
      </div>
    </main>
  );
}
