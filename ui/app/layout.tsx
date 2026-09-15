import type { Metadata } from "next";
import Link from "next/link";
import { SideNav } from "@/components/SideNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "prompt-graph",
  description: "Read-only view of the review-table prompt inventory",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen">
          <aside
            className="sticky top-0 hidden h-screen w-[210px] shrink-0 flex-col border-r px-3 py-4 md:flex"
            style={{ background: "var(--surface)" }}
          >
            <Link href="/" className="mb-5 flex items-center gap-2 px-2">
              <span
                className="grid h-6 w-6 place-items-center rounded-md text-[11px] font-bold text-white"
                style={{ background: "var(--accent)" }}
              >
                pg
              </span>
              <span className="text-[13px] font-semibold">prompt-graph</span>
            </Link>
            <SideNav />
            <div className="mt-auto px-2 text-[11px]" style={{ color: "var(--text-3)" }}>
              read-only view
            </div>
          </aside>
          <div className="min-w-0 flex-1">{children}</div>
        </div>
      </body>
    </html>
  );
}
