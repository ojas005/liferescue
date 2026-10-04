"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getApiClient, isTerminalState, type ApiClient, type RunResponse, type TimelineEvent } from "@/lib/api";

export type RunState = {
  /** Latest GET /api/runs/{id} snapshot (RunRecord + approvals). */
  snapshot: RunResponse | undefined;
  /** All timeline events received so far, ordered by seq. */
  events: TimelineEvent[];
  error: string | undefined;
  /** True once the first successful load finished. */
  loaded: boolean;
  /** True once the timeline reported terminal=true (polling stopped). */
  finished: boolean;
  /** Poll once now (also restarts the loop if it had stopped). */
  refresh: () => Promise<void>;
  /** Use a RunResponse returned by approve/deny/cancel immediately, then refresh the timeline. */
  applySnapshot: (r: RunResponse) => void;
};

function mergeEvents(prev: TimelineEvent[], incoming: TimelineEvent[]): TimelineEvent[] {
  if (incoming.length === 0) return prev;
  const bySeq = new Map(prev.map((e) => [e.seq, e]));
  for (const e of incoming) bySeq.set(e.seq, e);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/**
 * Poll GET /api/runs/{id} and GET /api/runs/{id}/timeline?after_seq=next_seq until the timeline reports
 * terminal=true. POST /api/runs may return a run still at INTENT or already advanced, so we always poll.
 * Transient errors keep polling with a gentle backoff. (SSE is deferred by the contract.)
 */
export function useRun(runId: string, options: { client?: ApiClient; intervalMs?: number } = {}): RunState {
  const { client, intervalMs = 1500 } = options;
  const [snapshot, setSnapshot] = useState<RunResponse>();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string>();
  const [loaded, setLoaded] = useState(false);
  const [finished, setFinished] = useState(false);
  const nextSeq = useRef(0);
  const failures = useRef(0);
  const tickRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    const api = client ?? getApiClient();
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    nextSeq.current = 0;

    const tick = async () => {
      let done = false;
      try {
        const [run, page] = await Promise.all([api.getRun(runId, ctrl.signal), api.getTimeline(runId, nextSeq.current, ctrl.signal)]);
        if (ctrl.signal.aborted) return;
        failures.current = 0;
        nextSeq.current = Math.max(nextSeq.current, page.next_seq);
        setSnapshot(run);
        setEvents((prev) => mergeEvents(prev, page.events));
        setError(undefined);
        setLoaded(true);
        done = page.terminal && isTerminalState(run.run.state);
        setFinished(done);
      } catch (err) {
        if (ctrl.signal.aborted) return;
        failures.current += 1;
        setError(err instanceof Error ? err.message : "Unknown error");
      }
      if (!done && !stopped) {
        const delay = Math.min(intervalMs * 2 ** Math.min(failures.current, 3), 10000);
        timer = setTimeout(tick, delay);
      }
    };
    tickRef.current = async () => {
      if (timer) clearTimeout(timer);
      await tick();
    };
    void tick();
    return () => {
      stopped = true;
      ctrl.abort();
      if (timer) clearTimeout(timer);
    };
  }, [runId, client, intervalMs]);

  const refresh = useCallback(() => tickRef.current(), []);
  const applySnapshot = useCallback((r: RunResponse) => setSnapshot(r), []);
  return { snapshot, events, error, loaded, finished, refresh, applySnapshot };
}
