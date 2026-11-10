import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

/** Load data, and optionally keep polling while `pollWhile(data)` is true. */
export function useLoad<T>(
  load: () => Promise<T>,
  deps: unknown[],
  pollWhile?: (data: T) => boolean,
  intervalMs = 1500,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(async () => {
    try {
      const result = await loadRef.current();
      setData(result);
      setError(null);
      return result;
    } catch (e) {
      setError(errorText(e));
      return null;
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    const tick = async () => {
      const result = await refresh();
      if (!stopped && pollWhile && result && pollWhile(result)) {
        timer = window.setTimeout(tick, intervalMs);
      }
    };
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, refresh, setData };
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
