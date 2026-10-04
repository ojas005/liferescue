"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { canCancel, getApiClient, isTerminalState, pendingApprovals, type ApiClient, type ApprovalDecision } from "@/lib/api";
import { useRun } from "@/hooks/useRun";
import { planRows } from "@/lib/run-view";
import { metaFor } from "@/lib/workflows/catalog";
import { ApprovalPrompt } from "./ApprovalPrompt";
import { EvidencePanel } from "./EvidencePanel";
import { PlanView } from "./PlanView";
import { ResultCard } from "./ResultCard";
import { StatusBadge } from "./StatusBadge";
import { Timeline } from "./Timeline";

/** One run page for ALL workflows: same components, data-driven by the contract. */
export function RunView({ runId, client, intervalMs }: { runId: string; client?: ApiClient; intervalMs?: number }) {
  const api = client ?? getApiClient();
  const { snapshot, events, error, loaded, finished, refresh, applySnapshot } = useRun(runId, { client: api, intervalMs });
  const [actionError, setActionError] = useState<string>();
  const [cancelling, setCancelling] = useState(false);

  const run = snapshot?.run;
  const pending = useMemo(() => pendingApprovals(snapshot), [snapshot]);
  const rows = useMemo(() => planRows(snapshot), [snapshot]);

  const onDecide = useCallback(
    async (approvalId: string, decision: ApprovalDecision, reason?: string) => {
      setActionError(undefined);
      const next = await api.decideApproval(runId, approvalId, decision, reason);
      applySnapshot(next);
      await refresh();
    },
    [api, runId, refresh, applySnapshot],
  );

  async function onCancel() {
    setCancelling(true);
    setActionError(undefined);
    try {
      const next = await api.cancelRun(runId);
      applySnapshot(next);
      await refresh();
    } catch (err) {
      // 409: cancel is only allowed before ACTION. Shown as text.
      setActionError(err instanceof Error ? err.message : "Could not cancel");
    } finally {
      setCancelling(false);
    }
  }

  const meta = run ? metaFor(run.workflow_id) : undefined;
  const cancellable = run ? canCancel(run.state) && !isTerminalState(run.state) : false;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold text-slate-900">{meta ? `${meta.product} run` : "Run"}</h1>
        {run ? <StatusBadge status={run.state} /> : null}
        <span className="text-xs text-slate-500">
          id: <code>{runId}</code>
        </span>
        <div className="ml-auto flex items-center gap-3">
          {cancellable ? (
            <button
              type="button"
              onClick={() => void onCancel()}
              disabled={cancelling}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-100 disabled:opacity-50"
              title="Cancel is only possible before the action starts"
            >
              {cancelling ? "Cancelling..." : "Cancel run"}
            </button>
          ) : null}
          <Link href="/" className="text-sm text-slate-600 underline">
            Home
          </Link>
        </div>
      </div>

      {error ? (
        <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          {loaded ? "Connection problem, retrying: " : "Could not load this run: "}
          {error}
        </p>
      ) : null}
      {actionError ? (
        <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          {actionError}
        </p>
      ) : null}

      {!loaded && !error ? (
        <p role="status" className="text-sm text-slate-600">
          Loading run...
        </p>
      ) : null}

      {pending.map((a) => (
        <ApprovalPrompt key={a.approval_id} approval={a} step={rows.find((r) => r.stepId === a.step_id)} onDecide={onDecide} />
      ))}

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <section aria-labelledby="timeline-h" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 id="timeline-h" className="mb-4 text-sm font-semibold text-slate-900">
            Timeline
          </h2>
          <Timeline events={events} live={loaded && !finished} />
        </section>
        <div className="space-y-6">
          <ResultCard snapshot={snapshot} />
          <PlanView snapshot={snapshot} />
          <EvidencePanel events={events} input={run?.input} />
        </div>
      </div>
    </div>
  );
}
