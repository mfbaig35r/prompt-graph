"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getMatters } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    getMatters()
      .then((r) => r.matters[0] && router.replace(`/m/${encodeURIComponent(r.matters[0].name)}`))
      .catch(() => {});
  }, [router]);
  return (
    <main className="px-8 py-8" style={{ color: "var(--text-3)" }}>
      Loading…
    </main>
  );
}
