import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

// Pages report each successful refresh here so the top bar can show
// "Live · updated 12s ago" (or warn when refreshes are failing).
export interface LiveState {
  updatedAt: number | null;
  failing: boolean;
}
export const LiveContext = createContext<(s: LiveState) => void>(() => {});

/** Loads `fn` now and then every `intervalMs`, pausing while the tab is hidden. */
export function usePolling<T>(fn: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const report = useContext(LiveContext);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const load = useCallback(async () => {
    try {
      const result = await fnRef.current();
      setData(result);
      setError(null);
      report({ updatedAt: Date.now(), failing: false });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      report({ updatedAt: null, failing: true });
    }
  }, [report]);

  useEffect(() => {
    load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load, intervalMs]);

  return { data, error, reload: load };
}

/** Current time in seconds, ticking every `everyMs`. */
export function useNow(everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), everyMs);
    return () => window.clearInterval(id);
  }, [everyMs]);
  return now;
}
