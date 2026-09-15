"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Briefcase, GitCompare, LayoutDashboard, Layers } from "lucide-react";
import { getMatter, getMatters, type Matter } from "@/lib/api";

export function SideNav() {
  const path = usePathname();
  const [names, setNames] = useState<string[]>([]);
  const [m, setM] = useState<Matter | null>(null);

  const active = decodeURIComponent(path.split("/")[2] ?? "");
  const activeTable = decodeURIComponent(path.split("/")[4] ?? "");

  useEffect(() => {
    getMatters().then((r) => setNames(r.matters.map((x) => x.name))).catch(() => {});
  }, []);
  useEffect(() => {
    if (!active) return;
    // Guard the response: navigating between matters can land an older fetch last.
    let alive = true;
    getMatter(active)
      .then((x) => alive && setM(x))
      .catch(() => alive && setM(null));
    return () => {
      alive = false;
    };
  }, [active]);

  // Cleared declaratively rather than by setting state in the effect above.
  if (!m || !active) return null;
  const base = `/m/${encodeURIComponent(m.matter)}`;

  return (
    <>
      <div className="eyebrow flex items-center gap-1.5 px-2"><Briefcase size={12} strokeWidth={2.25} />Matter</div>
      <div className="mb-3 px-2 text-[12.5px] font-medium">{m.matter}</div>

      <nav className="mb-4">
        {[
          { href: base, label: "Overview", icon: LayoutDashboard },
          { href: `${base}/concepts`, label: "Consistency", icon: GitCompare },
        ].map(({ href, label, icon: Icon }) => {
          const on = path === href;
          return (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-2 rounded-md px-2 py-[5px] text-[12.5px]"
              style={{ background: on ? "var(--accent-soft)" : "transparent", color: on ? "var(--accent)" : "var(--text-2)" }}
            >
              <Icon size={13} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="eyebrow flex items-center justify-between px-2">
        <span className="flex items-center gap-1.5"><Layers size={12} strokeWidth={2.25} />Modules</span>
        <span className="mono" style={{ color: "var(--text-3)" }}>{m.table_count}</span>
      </div>
      <nav className="-mx-1 mt-1 min-h-0 flex-1 overflow-y-auto px-1">
        {m.tables.map((t) => {
          const href = `${base}/t/${encodeURIComponent(t.table)}`;
          const on = activeTable === t.table;
          return (
            <Link
              key={t.table}
              href={href}
              className="flex items-baseline justify-between gap-2 rounded-md px-2 py-[5px] text-[12px]"
              style={{ background: on ? "var(--accent-soft)" : "transparent", color: on ? "var(--accent)" : "var(--text-2)" }}
            >
              <span className="truncate">{t.table}</span>
              <span className="mono shrink-0 text-[10.5px]" style={{ color: "var(--text-3)" }}>{t.columns}</span>
            </Link>
          );
        })}
      </nav>

      {names.length > 1 && (
        <div className="mt-3 border-t pt-3">
          <div className="eyebrow px-2">Other matters</div>
          {names.filter((n) => n !== m.matter).map((n) => (
            <Link key={n} href={`/m/${encodeURIComponent(n)}`} className="block truncate px-2 py-1 text-[12px]" style={{ color: "var(--text-2)" }}>
              {n}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
