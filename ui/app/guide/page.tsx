"use client";

import Link from "next/link";
import { BookOpen, CircleSlash, GitCompare, LayoutDashboard, ScrollText, Table2 } from "lucide-react";
import { PageHeader, Panel } from "@/components/ui";
import { GLOSSARY } from "@/lib/glossary";

/** Grouped by what a reader is looking at when they need the word, not alphabetically. The
 *  definitions themselves come from lib/glossary.ts, which is what the tooltips read, so the
 *  guide and the hover text can never disagree. */
const GROUPS: { title: string; blurb: string; keys: string[] }[] = [
  {
    title: "What a rule is",
    blurb: "Every question in the review is one rule, with a type that fixes the shape of its answer.",
    keys: ["native_type", "Classify", "FreeResponse", "Verbatim", "Date", "Number", "Currency", "Duration"],
  },
  {
    title: "When a rule runs",
    blurb: "Rules are staged. Earlier stages establish what the row is so later ones can rely on it.",
    keys: ["role", "orientation", "extraction", "validation", "reconciliation", "human_review"],
  },
  {
    title: "Where a rule is in its life",
    blurb: "Status is the rule's own lifecycle. Staleness is whether its last recorded result still holds.",
    keys: ["status", "draft", "testing", "verified", "retired", "staleness", "never_run", "current", "stale_direct", "stale_transitive", "open_failures"],
  },
  {
    title: "How rules connect",
    blurb: "One prompt can read another's answer. That is what makes a change ripple.",
    keys: ["reference_graph", "degree", "review_unit", "not_referenced"],
  },
  {
    title: "Where they disagree",
    blurb: "The same legal question, asked in more than one module, answered from a different menu.",
    keys: ["divergent_rules", "distinct_option_sets", "agreed_by_all", "name_variant"],
  },
  {
    title: "Defects the checks report",
    blurb: "Findings are factual observations with evidence attached. There is no pass or fail anywhere.",
    keys: ["DEAD_REFERENCE", "FALLBACK_NOT_STATED_UNTYPED", "FALLBACK_NOT_ADDRESSED_TYPED", "FALLBACK_SYNONYM", "CLASSIFY_LABEL_NOT_CONFIGURED", "CONTROL_PLANE_NARRATIVE", "PROMPT_LENGTH_ADVISORY", "CONCEPT_NAME_VARIANT", "CONCEPT_DIVERGENT_RULES", "CURRENCY_PATTERN_DIVERGENT", "COLUMN_NOT_VERIFIED", "COLUMN_STALE"],
  },
];

const PAGES = [
  { icon: LayoutDashboard, name: "Overview", href: "", what: "Every module, how many rules each holds, and whether anything has run." },
  { icon: ScrollText, name: "Requirements", href: "/requirements", what: "The external specification the suite was built to satisfy, and what each item resolved to." },
  { icon: BookOpen, name: "Correlation", href: "/coverage", what: "What the memo has to be able to say, and which rules supply the evidence." },
  { icon: GitCompare, name: "Consistency", href: "/concepts", what: "Where the same question is answered from a different menu in different modules." },
  { icon: Table2, name: "A module", href: "", what: "Its rules, how they reference each other, and everything the checks found in it." },
];

export default function GuidePage() {
  return (
    <main className="mx-auto w-full max-w-[1100px] px-10 py-10">
      <PageHeader
        title="How this fits together"
        description="A review table turns documents into cells. This holds the rules that do it: their history, how they connect, what they are supposed to support, and what is wrong with them. It never runs a review and never makes a legal call."
      />

      <Panel title="The chain" icon={BookOpen} className="mb-7">
        <div className="overflow-x-auto px-5 py-5">
          <Chain />
        </div>
        <p className="border-t px-5 py-3.5 text-[12.5px]" style={{ color: "var(--text-2)" }}>
          Read it in either direction. Left to right asks{" "}
          <em>does the specification survive all the way down to a cell?</em> Right to left asks{" "}
          <em>why does this rule exist at all?</em> Both are one click on any rule page.
        </p>
      </Panel>

      <Panel title="The pages" icon={LayoutDashboard} className="mb-7">
        {PAGES.map((p) => (
          <div key={p.name} className="flex items-start gap-3 border-b px-5 py-3 last:border-b-0">
            <span className="mt-0.5 shrink-0" style={{ color: "var(--text-3)" }}>
              <p.icon size={14} />
            </span>
            <span className="min-w-0">
              <span className="block text-[12.5px] font-medium">{p.name}</span>
              <span className="block text-[12.5px]" style={{ color: "var(--text-2)" }}>{p.what}</span>
            </span>
          </div>
        ))}
      </Panel>

      <Panel title="What it does not do" icon={CircleSlash} className="mb-7">
        <ul className="space-y-1.5 px-5 py-3.5 text-[12.5px]" style={{ color: "var(--text-2)" }}>
          <li>It never writes or rewrites a rule.</li>
          <li>It never runs a review and never reads a source document.</li>
          <li>
            It never makes a legal determination. Whether a finding matters is a judgment, so
            every output is an observation with its evidence, and there is no verdict anywhere.
          </li>
          <li>This view is read-only by construction: the database refuses writes on it.</li>
        </ul>
      </Panel>

      <h2 className="mb-3 mt-10 text-[15px] font-semibold">Reference</h2>
      <p className="mb-5 max-w-3xl text-[13px]" style={{ color: "var(--text-2)" }}>
        Every term below is also defined where it appears: anything with a dotted underline
        explains itself on hover.
      </p>

      <div className="space-y-7">
        {GROUPS.map((g) => (
          <section key={g.title}>
            <h3 className="text-[13px] font-medium">{g.title}</h3>
            <p className="mb-2.5 text-[12.5px]" style={{ color: "var(--text-3)" }}>{g.blurb}</p>
            <div className="card divide-y overflow-hidden">
              {g.keys.filter((k) => GLOSSARY[k]).map((k) => (
                <div key={k} className="flex flex-col gap-1 px-5 py-2.5 sm:flex-row sm:gap-5">
                  <span className="shrink-0 text-[12.5px] font-medium sm:w-[190px]">
                    {GLOSSARY[k].title}
                  </span>
                  <span className="text-[12.5px]" style={{ color: "var(--text-2)" }}>
                    {ticks(GLOSSARY[k].body)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      <p className="mt-10 text-[12.5px]" style={{ color: "var(--text-3)" }}>
        <Link href="/" className="hover:underline" style={{ color: "var(--accent)" }}>
          Back to the matter
        </Link>
      </p>
    </main>
  );
}

/** The glossary bodies are written for tooltips and mark literals with backticks. Inline they are
 *  near-invisible; on a reference page they read as typos, so render them as code. */
function ticks(s: string) {
  return s.split("`").map((part, i) =>
    i % 2 === 1 ? (
      <code key={i} className="mono rounded px-1 py-px text-[11.5px]" style={{ background: "var(--surface-2)", color: "var(--text)" }}>
        {part}
      </code>
    ) : (
      part
    ),
  );
}

const STEPS = [
  { label: "Requirement", sub: "the specification", page: "Requirements" },
  { label: "Assertion", sub: "what the memo must say", page: "Correlation" },
  { label: "Rule", sub: "the question asked", page: "A module" },
  { label: "Prompt", sub: "the instruction, versioned", page: "A rule" },
  { label: "Cell", sub: "the answer, in Harvey", page: "not here" },
];

function Chain() {
  const W = 178;
  const GAP = 26;
  return (
    <svg width={STEPS.length * W + (STEPS.length - 1) * GAP} height={96} role="img" aria-label="requirement to assertion to rule to prompt to cell">
      {STEPS.map((s, i) => {
        const x = i * (W + GAP);
        const outside = s.page === "not here";
        return (
          <g key={s.label}>
            {i > 0 && (
              <path
                d={`M${x - GAP + 3},44 L${x - 5},44`}
                stroke="var(--edge)"
                strokeWidth={1.2}
                markerEnd="url(#gtip)"
              />
            )}
            <rect
              x={x} y={20} width={W} height={48} rx={9}
              fill="var(--surface)"
              stroke={outside ? "var(--border)" : "var(--accent)"}
              strokeDasharray={outside ? "4 3" : undefined}
            />
            <text x={x + 14} y={41} fontSize="12.5" fontWeight="500" fill="var(--text)">{s.label}</text>
            <text x={x + 14} y={57} fontSize="11" fill="var(--text-3)">{s.sub}</text>
            <text x={x + 14} y={86} fontSize="10.5" fill={outside ? "var(--text-3)" : "var(--accent)"}>
              {outside ? "outside this tool" : s.page}
            </text>
          </g>
        );
      })}
      <defs>
        <marker id="gtip" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L5,3 L0,6 z" fill="var(--edge)" />
        </marker>
      </defs>
    </svg>
  );
}
