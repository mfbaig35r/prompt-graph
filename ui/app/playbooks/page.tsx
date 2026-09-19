"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BookMarked, FileText, GitCompare } from "lucide-react";
import { PageHeader, Panel } from "@/components/ui";
import { getPlaybooks } from "@/lib/api";

export default function PlaybooksPage() {
  const [d, setD] = useState<Awaited<ReturnType<typeof getPlaybooks>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    getPlaybooks().then(setD).catch((e) => setErr(String(e)));
  }, []);

  if (err)
    return (
      <main className="mx-auto w-full max-w-[1100px] px-10 py-10" style={{ color: "var(--stop)" }}>
        {err}
      </main>
    );
  if (!d)
    return (
      <main className="mx-auto w-full max-w-[1100px] px-10 py-10" style={{ color: "var(--text-3)" }}>
        Loading…
      </main>
    );

  return (
    <main className="mx-auto w-full max-w-[1100px] px-10 py-10">
      <PageHeader
        title="Playbooks"
        description="Read from a directory and checked against the authoring format. Nothing here is stored: each is parsed when you open it, so the file on disk is always what you are looking at."
        right={
          <Link href="/playbooks/diff" className="btn flex items-center gap-1.5">
            <GitCompare size={13} /> Compare two versions
          </Link>
        }
      />
      <Panel title="Files" icon={BookMarked}>
        {d.playbooks.length === 0 && (
          <p className="px-5 py-4 text-[12.5px]" style={{ color: "var(--text-3)" }}>
            No .docx or .md files in that directory.
          </p>
        )}
        {d.playbooks.map((p) => (
          <Link
            key={p.name}
            href={`/playbooks/${encodeURIComponent(p.name)}`}
            className="rowlink flex items-center gap-3 border-b px-5 py-3 last:border-b-0"
          >
            <FileText size={14} className="shrink-0" style={{ color: "var(--text-3)" }} />
            <span className="min-w-0 flex-1 truncate text-[12.5px]">{p.name}</span>
            <span className="mono shrink-0 text-[11px]" style={{ color: "var(--text-3)" }}>
              {Math.round(p.bytes / 1024)} KB
            </span>
          </Link>
        ))}
      </Panel>
    </main>
  );
}
