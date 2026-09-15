"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { lookup } from "@/lib/glossary";

/** Fixed-position tooltip. Rendered against the viewport rather than inside the flow, because
 *  most of these terms sit in `overflow-x-auto` tables where an absolute popover gets clipped. */
export function Term({
  k,
  children,
  underline = true,
}: {
  k: string;
  children?: React.ReactNode;
  underline?: boolean;
}) {
  const entry = lookup(k);
  const ref = useRef<HTMLSpanElement>(null);
  const [box, setBox] = useState<{ x: number; y: number; above: boolean } | null>(null);

  const hide = useCallback(() => setBox(null), []);

  // Coordinates are captured once, so any scroll or resize strands the tooltip away from the
  // term it belongs to. Capture phase, because the page has inner scrollers too.
  useEffect(() => {
    if (!box) return;
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [box, hide]);

  const show = useCallback(() => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    // The UI is scaled with CSS `zoom`. getBoundingClientRect reports post-zoom (visual)
    // coordinates, but a fixed child inside the zoomed subtree has its own left/top multiplied
    // by that same factor, so the raw values land the tooltip short of its term. Divide back out.
    const z =
      parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ui-scale")) || 1;
    const above = r.top > 190;
    const cx = Math.min(Math.max(r.left + r.width / 2, 150), window.innerWidth - 150);
    setBox({ x: cx / z, y: (above ? r.top - 8 : r.bottom + 8) / z, above });
  }, []);

  if (!entry) return <>{children}</>;

  return (
    <>
      <span
        ref={ref}
        tabIndex={0}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        className="cursor-help outline-none"
        style={
          underline
            ? { textDecoration: "underline dotted", textDecorationColor: "var(--border-2)", textUnderlineOffset: 3 }
            : undefined
        }
      >
        {children}
      </span>
      {box && (
        <span
          role="tooltip"
          className="pointer-events-none fixed z-50 block w-[280px] rounded-lg border px-3 py-2 text-[12.5px] leading-[1.5]"
          style={{
            left: box.x,
            top: box.y,
            transform: `translate(-50%, ${box.above ? "-100%" : "0"})`,
            // Never inherit: these terms sit inside .mono code spans and inside .eyebrow,
            // which uppercases and letter-spaces. The `font` shorthand covers neither of those.
            font: '400 12px/1.5 ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif',
            textTransform: "none",
            letterSpacing: "normal",
            background: "var(--surface)",
            borderColor: "var(--border-2)",
            color: "var(--text-2)",
            boxShadow: "0 4px 16px rgba(16,24,40,0.12)",
          }}
        >
          <span className="mb-0.5 block font-semibold" style={{ color: "var(--text)" }}>
            {entry.title}
          </span>
          {entry.body}
        </span>
      )}
    </>
  );
}
