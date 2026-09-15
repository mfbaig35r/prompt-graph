import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Term } from "./Tip";

export function Pill({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn" | "stop" | "accent"; children: React.ReactNode }) {
  const map = {
    neutral: ["var(--surface-2)", "var(--text-2)"],
    ok: ["var(--ok-soft)", "var(--ok)"],
    warn: ["var(--warn-soft)", "var(--warn)"],
    stop: ["var(--stop-soft)", "var(--stop)"],
    accent: ["var(--accent-soft)", "var(--accent)"],
  }[tone];
  return (
    <span className="pill" style={{ background: map[0], color: map[1] }}>
      {children}
    </span>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>;
}

export function Eyebrow({
  children,
  icon: Icon,
  className = "",
}: {
  children: React.ReactNode;
  icon?: React.ComponentType<{ size?: number | string; strokeWidth?: number | string; className?: string }>;
  className?: string;
}) {
  return (
    <div className={`eyebrow mb-2 flex items-center gap-1.5 ${className}`}>
      {Icon && <Icon size={12} strokeWidth={2.25} />}
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  tone,
  icon: Icon,
  termKey,
}: {
  label: string;
  termKey?: string;
  value: number | string;
  tone?: "warn" | "stop" | "ok";
  icon?: React.ComponentType<{ size?: number | string; strokeWidth?: number | string }>;
}) {
  const color = tone === "stop" ? "var(--stop)" : tone === "warn" ? "var(--warn)" : tone === "ok" ? "var(--ok)" : "var(--text)";
  return (
    <div className="card px-4 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="mono text-[20px] font-semibold leading-none" style={{ color }}>{value}</div>
        {Icon && <span style={{ color: "var(--text-3)" }}><Icon size={14} strokeWidth={2} /></span>}
      </div>
      <div className="eyebrow mt-1.5 mb-0">{termKey ? <Term k={termKey}>{label}</Term> : label}</div>
    </div>
  );
}

export function Crumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav className="mb-3 flex flex-wrap items-center gap-1.5 text-[12px]" style={{ color: "var(--text-3)" }}>
      {items.map((it, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <ChevronRight size={12} style={{ color: "var(--border-2)" }} />}
          {it.href ? (
            <Link href={it.href} className="hover:underline" style={{ color: "var(--text-2)" }}>{it.label}</Link>
          ) : (
            <span style={{ color: "var(--text)" }}>{it.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

export function GoChevron() {
  return <ChevronRight size={13} style={{ color: "var(--text-3)" }} className="shrink-0" />;
}

export function PageHeader({
  title,
  description,
  right,
  crumbs,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  right?: React.ReactNode;
  crumbs?: { label: string; href?: string }[];
}) {
  return (
    <div className="mb-6">
      {crumbs && <Crumbs items={crumbs} />}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-[21px] font-semibold tracking-[-0.015em]">{title}</h1>
          {description && (
            <p className="mt-1 max-w-3xl text-[13px]" style={{ color: "var(--text-2)" }}>
              {description}
            </p>
          )}
        </div>
        {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
      </div>
    </div>
  );
}

export function Panel({
  title,
  right,
  children,
  className = "",
  bodyClassName = "",
  icon: Icon,
}: {
  title: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  icon?: React.ComponentType<{ size?: number | string; strokeWidth?: number | string }>;
}) {
  return (
    <section className={`card overflow-hidden ${className}`}>
      <div
        className="flex items-center justify-between gap-3 border-b px-4 py-2.5"
        style={{ background: "var(--surface-2)" }}
      >
        <span className="eyebrow flex items-center gap-1.5">
          {Icon && <Icon size={12} strokeWidth={2.25} />}
          {title}
        </span>
        {right}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={o.value} data-on={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function statusTone(s: string) {
  return s === "verified" ? "ok" : s === "testing" ? "warn" : s === "retired" ? "stop" : "neutral";
}
