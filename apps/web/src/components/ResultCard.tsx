import type { RunResponse } from "@/lib/api/schemas";
import { isTerminalState } from "@/lib/api/schemas";
import { PayloadView } from "./PayloadView";
import { SafeText } from "./SafeText";
import { StatusBadge } from "./StatusBadge";

/** Final result for ANY workflow: outcome state, reason, tool results (simulated ones labelled) and verification. */
export function ResultCard({ snapshot }: { snapshot: RunResponse | undefined }) {
  const run = snapshot?.run;
  const done = run ? isTerminalState(run.state) : false;
  return (
    <section aria-labelledby="result-h" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 id="result-h" className="text-sm font-semibold text-slate-900">
          Result
        </h2>
        {run ? <StatusBadge status={run.state} /> : null}
      </div>
      {!run ? (
        <p className="mt-3 text-sm text-slate-600">Loading...</p>
      ) : (
        <div className="mt-3 space-y-4">
          {run.intent ? (
            <p className="text-sm text-slate-800">
              <SafeText text={run.intent.summary} />
            </p>
          ) : null}
          {!done ? <p className="text-sm text-slate-600">The final result will appear here when the run finishes.</p> : null}
          {done && run.terminal_reason ? (
            <p className="text-sm font-medium text-slate-900" data-testid="terminal-reason">
              <SafeText text={run.terminal_reason} />
            </p>
          ) : null}
          {run.results.length > 0 ? (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Tool results</h3>
              <ul className="mt-1 space-y-2">
                {run.results.map((r, i) => (
                  <li key={`${r.tool_name}-${i}`} data-testid="tool-result" className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs">{r.tool_name}</span>
                      <StatusBadge status={r.status === "ok" ? "completed" : "failed"} kind="plain" />
                      {r.mocked ? (
                        <span data-testid="simulated-badge" className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-bold uppercase text-amber-900">
                          simulated
                        </span>
                      ) : null}
                    </div>
                    {Object.keys(r.output).length > 0 ? (
                      <div className="mt-1">
                        <PayloadView value={r.output} />
                      </div>
                    ) : null}
                    {r.error ? (
                      <p className="mt-1 text-xs text-rose-800">
                        <SafeText text={r.error} />
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {run.verification ? (
            <div data-testid="verification">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                Verification: {run.verification.passed ? "passed" : "failed"}
              </h3>
              <ul className="mt-1 space-y-1 text-sm">
                {run.verification.checks.map((c) => (
                  <li key={c.check_id}>
                    <span aria-hidden>{c.passed ? "\u2713" : "\u2717"}</span> <span className="sr-only">{c.passed ? "passed" : "failed"}: </span>
                    <span className="font-mono text-xs">{c.check_id}</span> &ndash; <SafeText text={c.detail} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
