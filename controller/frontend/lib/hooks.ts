"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type State<T> = { data: T | undefined; error: unknown; loading: boolean };

/**
 * Fetch data, optionally re-polling while `poll(data)` returns an interval in ms.
 * Keeps previous data on refetch so the UI never flashes back to a skeleton.
 */
export function useResource<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
  options: { poll?: (data: T | undefined) => number | false } = {},
) {
  const [state, setState] = useState<State<T>>({ data: undefined, error: null, loading: true });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const pollRef = useRef(options.poll);
  pollRef.current = options.poll;
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const run = async () => {
      try {
        const data = await fetcherRef.current();
        if (!alive) return;
        setState({ data, error: null, loading: false });
        const next = pollRef.current?.(data);
        if (next) timer = setTimeout(run, next);
      } catch (error) {
        if (!alive) return;
        setState((s) => ({ ...s, error, loading: false }));
        const next = pollRef.current?.(undefined);
        if (next) timer = setTimeout(run, Math.max(next, 5000));
      }
    };
    setState((s) => ({ ...s, loading: true }));
    run();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const mutate = useCallback((fn: (d: T | undefined) => T | undefined) => {
    setState((s) => ({ ...s, data: fn(s.data) }));
  }, []);

  return { ...state, reload, mutate };
}

export function useDebounced<T>(value: T, delay = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

/** Stable "now" that re-renders every `interval` ms, for relative timestamps. */
export function useNow(interval = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(t);
  }, [interval]);
  return now;
}
