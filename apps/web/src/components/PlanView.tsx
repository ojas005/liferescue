import type { RunResponse } from "@/lib/api/schemas";
import { planRows } from "@/lib/run-view";
import { PayloadView } from "./PayloadView";
import { SafeText } from "./SafeText";

const OUTCOME_STYLE: Record<string, string> = {
  allow: "bg-emerald-50 text-emerald-900",
  needs_approval: "bg-amber-50 text-amber-900",
  deny: "bg-rose-50 text-rose-900",
};

export function PlanView({ snapshot }: { snapshot: RunResponse | undefined }) {
  const rows = planRows(snapshot);
  return (
    <section aria-labelledby="plan-h" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 id="plan-h" className="text-sm font-semibold text-slate-900">
        Plan
      </h2>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-slate-600">No plan yet.</p>
      ) : (
        <ol className="mt-3 space-y-2">
          {rows.map((s, i) => (
            <li key={s.stepId} data-testid="plan-step" className="flex gap-3 rounded-lg border border-slate-200 p-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-900">
                  <SafeText text={s.rationale} />
                </p>
                <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-600">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5">{s.actionType}</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono">{s.toolName}</span>
                  {s.outcome ? (
                    <span className={`rounded px-1.5 py-0.5 ${OUTCOME_STYLE[s.outcome] ?? "bg-slate-100"}`} title={s.reason}>
                      policy: {s.outcome.replace("_", " ")}
                      {s.risk ? ` (${s.risk} risk)` : ""}
                    </span>
                  ) : null}
                </div>
                {Object.keys(s.params).length > 0 ? (
                  <div className="mt-2 rounded border border-slate-200 bg-slate-50 p-2">
                    <PayloadView value={s.params} />
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
