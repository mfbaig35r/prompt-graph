"use client";

import { useEffect, useState } from "react";
import { ArrowRight, GitCompare, Minus, Pencil, Plus } from "lucide-react";
import { Eyebrow, PageHeader, Panel, Pill, Stat } from "@/components/ui";
import { getPlaybookDiff, getPlaybooks, type PlaybookDiff } from "@/lib/api";

export default function PlaybookDiffPage() {
  const [files, setFiles] = useState<string[]>([]);
  const [before, setBefore] = useState("");
  const [after, setAfter] = useState("");
  // keyed by the pair it describes, so a stale result never renders against a new selection
  // and the effect never has to null it out synchronously
  const [res, setRes] = useState<{ key: string; data: PlaybookDiff } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getPlaybooks()
      .then((r) => {
        const names = r.playbooks.map((p) => p.name);
        setFiles(names);
        if (names.length >= 2) {
          setBefore(names[0]);
          setAfter(names[1]);
        }
      })
      .catch((e) => setErr(String(e)));
  }, []);

  const pair = `${before}|${after}`;
  const ready = Boolean(before && after && before !== after);
  useEffect(() => {
    if (!ready) return;
    getPlaybookDiff(before, after)
      .then((data) => setRes({ key: `${before}|${after}`, data }))
      .catch((e) => setErr(String(e)));
  }, [before, after, ready]);

  const d = res && res.key === pair ? res.data : null;

  const sel = (v: string, on: (s: string) => void, label: string) => (
    <label className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="eyebrow mb-0">{label}</span>
      <select
        value={v}
        onChange={(e) => on(e.target.value)}
        className="min-w-0 truncate rounded-md px-3 py-2 text-[12.5px]"
        style={{ background: "var(--surface-2)", color: "var(--text)", border: "1px solid var(--border-2)" }}
      >
        <option value="">Select…</option>
        {files.map((f) => (
          <option key={f} value={f}>{f}</option>
        ))}
      </select>
    </label>
  );

  return (
    <main className="mx-auto w-full max-w-[1200px] px-10 py-10">
      <PageHeader
        title="Compare two versions"
        description="Harvey keys rules by name and has no stable identifier, so renaming one silently breaks every reference to it: dependencies written as Rule IDs, and precedence written in prose. Nothing in the platform detects that."
      />

      <div className="card mb-7 flex items-end gap-4 px-5 py-4">
        {sel(before, setBefore, "Before")}
        <ArrowRight size={15} className="mb-2.5 shrink-0" style={{ color: "var(--text-3)" }} />
        {sel(after, setAfter, "After")}
      </div>

      {files.length < 2 && (
        <p className="text-[12.5px]" style={{ color: "var(--text-3)" }}>
          Two files are needed. The configured directory holds {files.length}.
        </p>
      )}
      {err && <p className="text-[12.5px]" style={{ color: "var(--stop)" }}>{err}</p>}
      {before && after && before === after && (
        <p className="text-[12.5px]" style={{ color: "var(--text-3)" }}>
          Pick two different files.
        </p>
      )}

      {d && (
        <>
          <div className="mb-7 grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Stat label="Added" value={d.counts.added} icon={Plus} tone={d.counts.added ? "ok" : undefined} />
            <Stat label="Removed" value={d.counts.removed} icon={Minus} tone={d.counts.removed ? "warn" : undefined} />
            <Stat label="Renamed" value={d.counts.renamed} icon={Pencil} tone={d.counts.renamed ? "warn" : undefined} />
            <Stat label="Changed" value={d.counts.changed} icon={Pencil} />
            <Stat label="Unchanged" value={d.counts.unchanged} />
          </div>

          {d.findings.length === 0 ? (
            <div className="card mb-7 px-5 py-3.5 text-[12.5px]" style={{ color: "var(--text-2)" }}>
              Nothing in this revision left a reference pointing at something that is no longer
              there.
            </div>
          ) : (
            <Panel title={`What the revision broke · ${d.findings.length}`} icon={GitCompare} className="mb-7">
              {d.findings.map((f, i) => (
                <div key={i} className="border-b px-5 py-3 last:border-b-0">
                  <div className="flex items-baseline gap-3">
                    <span className="mono text-[10.5px]" style={{ color: "var(--warn)" }}>{f.code}</span>
                    <span className="text-[12.5px] font-medium">{f.subject_name}</span>
                  </div>
                  <div className="mt-0.5 text-[12.5px]" style={{ color: "var(--text-2)" }}>
                    {f.observation}
                  </div>
                </div>
              ))}
            </Panel>
          )}

          {d.renamed.length > 0 && (
            <Panel title="Renamed" icon={Pencil} className="mb-7">
              {d.renamed.map((r) => (
                <div key={r.from} className="flex flex-wrap items-center gap-2 border-b px-5 py-3 last:border-b-0 text-[12.5px]">
                  <span style={{ color: "var(--text-3)" }}>{r.from}</span>
                  <ArrowRight size={13} style={{ color: "var(--text-3)" }} />
                  <span className="font-medium">{r.to}</span>
                  <Pill tone={r.match >= 0.9 ? "ok" : "warn"}>
                    {r.match >= 1 ? "identical content" : `${Math.round(r.match * 100)}% content match`}
                  </Pill>
                </div>
              ))}
              <p className="border-t px-5 py-2.5 text-[12px]" style={{ color: "var(--text-3)" }}>
                Matched by Rule ID where the convention has been adopted, by content otherwise. A
                content match is an inference, not a fact, so its score is shown.
              </p>
            </Panel>
          )}

          <div className="grid grid-cols-1 gap-7 sm:grid-cols-3">
            {([["Added", d.added, Plus], ["Removed", d.removed, Minus], ["Changed", d.changed, Pencil]] as const).map(
              ([label, items, Icon]) => (
                <div key={label}>
                  <Eyebrow icon={Icon}>{label} · {items.length}</Eyebrow>
                  <div className="card mt-2 divide-y overflow-hidden">
                    {items.length === 0 && (
                      <p className="px-4 py-2.5 text-[12.5px]" style={{ color: "var(--text-3)" }}>none</p>
                    )}
                    {items.map((n) => (
                      <p key={n} className="px-4 py-2 text-[12.5px]">{n}</p>
                    ))}
                  </div>
                </div>
              ),
            )}
          </div>
        </>
      )}
    </main>
  );
}
