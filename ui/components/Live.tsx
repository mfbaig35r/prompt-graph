"use client";
import { useEffect, useRef, useState } from "react";
import { Radio, WifiOff } from "lucide-react";
import { getVersion } from "@/lib/api";

/** Polls PRAGMA data_version. It changes when the MCP server commits, which is the cue to
 *  refetch. One pragma per second is cheaper than re-running the overview query. */
export function useLiveVersion(onChange: () => void) {
  const [version, setVersion] = useState<number | null>(null);
  const [online, setOnline] = useState(true);
  const seen = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { data_version } = await getVersion();
        if (!alive) return;
        setOnline(true);
        setVersion(data_version);
        if (seen.current !== null && seen.current !== data_version) onChange();
        seen.current = data_version;
      } catch {
        if (alive) setOnline(false);
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [onChange]);

  return { version, online };
}

export function LiveDot({ online }: { online: boolean }) {
  return (
    <span
      className="pill shrink-0"
      style={{
        background: online ? "var(--ok-soft)" : "var(--stop-soft)",
        color: online ? "var(--ok)" : "var(--stop)",
      }}
    >
      {online ? <Radio size={11} /> : <WifiOff size={11} />}
      {online ? "live" : "api offline"}
    </span>
  );
}
