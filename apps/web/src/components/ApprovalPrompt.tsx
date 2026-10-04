"use client";

import { useId, useState } from "react";
import type { Approval, ApprovalDecision } from "@/lib/api/schemas";
import type { PlanRow } from "@/lib/run-view";
import { PayloadView } from "./PayloadView";
import { SafeText } from "./SafeText";

type Props = {
  /** An Approval with status "pending" from RunResponse.approvals. */
  approval: Approval;
  /** The plan step this approval is bound to (shows the EXACT tool and arguments being approved). */
  step?: PlanRow;
  onDecide: (approvalId: string, decision: ApprovalDecision, reason?: string) => Promise<void> | void;
  disabled?: boolean;
};

function formatExpiry(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString();
}

export function ApprovalPrompt({ approval, step, onDecide, disabled = false }: Props) {
  const uid = useId();
  const [busy, setBusy] = useState<ApprovalDecision | null>(null);
  const [error, setError] = useState<string>();
  const [reason, setReason] = useState("");

  async function decide(decision: ApprovalDecision) {
    setBusy(decision);
    setError(undefined);
    try {
      await onDecide(approval.approval_id, decision, reason.trim() || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record your decision");
    } finally {
      setBusy(null);
    }
  }

  const locked = disabled || busy !== null;
  return (
    <section
      role="alertdialog"
      aria-labelledby={`${uid}-h`}
      aria-describedby={`${uid}-d`}
      data-testid="approval-prompt"
      className="rounded-xl border-2 border-amber-400 bg-amber-50 p-4 shadow-sm"
    >
      <h2 id={`${uid}-h`} className="text-base font-semibold text-amber-950">
        Your approval is needed
      </h2>
      <div id={`${uid}-d`} className="mt-2 space-y-2 text-sm text-amber-950">
        <p className="font-medium">
          <SafeText text={approval.summary} />
        </p>
        <p className="text-xs uppercase tracking-wide">
          Risk: {approval.risk} &middot; step {approval.step_id} &middot; expires {formatExpiry(approval.expires_at)}
        </p>
        {step ? (
          <div className="rounded border border-amber-200 bg-white/70 p-2" data-testid="approval-step">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-900">
              Exact action: <span className="font-mono normal-case">{step.toolName}</span>
            </p>
            {step.reason ? (
              <p className="mt-1 text-xs">
                <SafeText text={step.reason} />
              </p>
            ) : null}
            <div className="mt-1">
              <PayloadView value={step.params} />
            </div>
          </div>
        ) : null}
        <p className="break-all text-[11px] text-amber-900">
          Approval is bound to digest <code>{approval.bound_digest.slice(0, 16)}</code>; it is single-use and void if the action changes.
        </p>
        <p className="text-xs text-amber-900">The run is paused until you decide. Nothing runs without your approval.</p>
      </div>
      <div className="mt-3">
        <label htmlFor={`${uid}-reason`} className="block text-xs font-medium text-amber-950">
          Reason (optional)
        </label>
        <input
          id={`${uid}-reason`}
          type="text"
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="mt-1 block w-full rounded border border-amber-300 bg-white px-2 py-1 text-sm"
        />
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm font-medium text-rose-800">
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex gap-3">
        <button
          type="button"
          disabled={locked}
          onClick={() => void decide("approve")}
          className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === "approve" ? "Approving..." : "Approve"}
        </button>
        <button
          type="button"
          disabled={locked}
          onClick={() => void decide("deny")}
          className="rounded-lg border border-rose-300 bg-white px-4 py-2 text-sm font-semibold text-rose-800 hover:bg-rose-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === "deny" ? "Denying..." : "Deny"}
        </button>
      </div>
    </section>
  );
}
