"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ChevronLeft, ChevronRight, GitCompare, LayoutDashboard, Layers, Moon, Sun,
} from "lucide-react";
import { getMatter, getMatters, type Matter } from "@/lib/api";

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [names, setNames] = useState<string[]>([]);
  const [m, setM] = useState<Matter | null>(null);

  const active = decodeURIComponent(path.split("/")[2] ?? "");
  const activeTable = decodeURIComponent(path.split("/")[4] ?? "");

  // localStorage does not exist during SSR, so persisted UI preferences can only be read after
  // mount. The inline script in layout.tsx has already applied the theme attribute by now; this
  // only syncs React's copy so the toggle renders the right icon.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => {
    setTheme((localStorage.getItem("pg-theme") as "dark" | "light") ?? "dark");
    setCollapsed(localStorage.getItem("pg-rail") === "1");
  }, []);

  useEffect(() => {
    getMatters().then((r) => setNames(r.matters.map((x) => x.name))).catch(() => {});
  }, []);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    getMatter(active).then((x) => alive && setM(x)).catch(() => alive && setM(null));
    return () => {
      alive = false;
    };
  }, [active]);

  const flip = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("pg-theme", next);
    } catch {}
  };
  const toggleRail = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem("pg-rail", next ? "1" : "0");
    } catch {}
  };

  const base = m ? `/m/${encodeURIComponent(m.matter)}` : "/";
  const nav = [
    { href: base, label: "Overview", icon: LayoutDashboard },
    { href: `${base}/concepts`, label: "Consistency", icon: GitCompare },
  ];

  return (
    <div className="flex min-h-screen">
      <aside
        className="sticky top-0 flex h-screen shrink-0 flex-col transition-[width] duration-150"
        style={{ width: collapsed ? 60 : 224, background: "var(--rail)" }}
      >
        <div className="flex items-center gap-2.5 px-3.5 py-4">
          <span
            className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[11px] font-bold"
            style={{ background: "var(--accent)", color: "var(--accent-ink)" }}
          >
            pg
          </span>
          {!collapsed && (
            <span className="min-w-0 flex-1">
              <span className="block text-[9.5px] font-semibold uppercase tracking-[0.1em]" style={{ color: "#5d7189" }}>
                Workbench
              </span>
              <span className="block truncate text-[13px] font-semibold" style={{ color: "#e7eef7" }}>
                prompt-graph
              </span>
            </span>
          )}
          <button
            onClick={toggleRail}
            className="grid h-6 w-6 shrink-0 place-items-center rounded-md"
            style={{ background: "rgba(255,255,255,0.05)", color: "#8fa3bb" }}
            aria-label={collapsed ? "Expand" : "Collapse"}
          >
            {collapsed ? <ChevronRight size={13} /> : <ChevronLeft size={13} />}
          </button>
        </div>

        <nav className="flex flex-col gap-0.5 px-2.5">
          {nav.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className="navitem" data-on={path === href} title={label}>
              <Icon size={15} className="shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </Link>
          ))}
        </nav>

        {!collapsed && m && (
          <>
            <div className="mt-5 flex items-center justify-between px-4">
              <span className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em]" style={{ color: "#5d7189" }}>
                <Layers size={11} /> Modules
              </span>
              <span className="mono text-[10.5px]" style={{ color: "#5d7189" }}>{m.table_count}</span>
            </div>
            <div className="mt-1 min-h-0 flex-1 overflow-y-auto px-2.5 pb-3">
              {m.tables.map((t) => {
                const href = `${base}/t/${encodeURIComponent(t.table)}`;
                return (
                  <Link key={t.table} href={href} className="navitem justify-between !py-[5px]" data-on={activeTable === t.table} title={t.table}>
                    <span className="truncate text-[12px]">{t.table}</span>
                    <span className="mono shrink-0 text-[10px] opacity-60">{t.columns}</span>
                  </Link>
                );
              })}
            </div>
          </>
        )}

        <div className={`mt-auto flex items-center gap-2 border-t px-3 py-3 ${collapsed ? "justify-center" : ""}`} style={{ borderColor: "rgba(255,255,255,0.07)" }}>
          <button onClick={flip} className="grid h-7 w-7 place-items-center rounded-md" style={{ background: "rgba(255,255,255,0.05)", color: "#8fa3bb" }} aria-label="Toggle theme">
            {theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}
          </button>
          {!collapsed && <span className="text-[11px]" style={{ color: "#5d7189" }}>read-only</span>}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b px-7 py-3" style={{ background: "var(--bg-2)" }}>
          <div className="min-w-0">
            <div className="eyebrow">Matter</div>
            <div className="truncate text-[15px] font-semibold">{m?.matter ?? "prompt-graph"}</div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {names.length > 1 && (
              <span className="pill" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>
                {names.length} matters
              </span>
            )}
            <span className="pill" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>Local</span>
          </div>
        </header>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
