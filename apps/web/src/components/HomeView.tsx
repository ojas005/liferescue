"use client";

import { useWorkflows } from "@/hooks/useWorkflows";
import { mergeWorkflows } from "@/lib/workflows/catalog";
import { WorkflowCard } from "./WorkflowCard";

export function HomeView() {
  const { workflows, loading, error } = useWorkflows();
  const entries = mergeWorkflows(workflows);
  return (
    <div className="space-y-10">
      <section className="space-y-4 pt-4">
        <h1 className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">One platform. Three ways it helps.</h1>
        <p className="max-w-2xl text-lg text-slate-700">
          LifeRescue, ScamShield and LifeOS run on the same engine: understand your request, gather evidence, plan, check policy, ask for your
          approval, act, verify, and keep an audit trail. Pick an experience to start.
        </p>
      </section>

      {error ? (
        <p role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
          Could not reach the workflows API ({error}). The descriptions below are built in; starting a run needs the API.
        </p>
      ) : null}
      {loading ? <p role="status" className="text-sm text-slate-600">Checking available workflows...</p> : null}

      <section aria-label="Experiences" className="grid gap-6 md:grid-cols-3">
        {entries.map((e) => (
          <WorkflowCard key={e.workflowId} meta={e.meta} available={loading || !!error ? true : !!e.workflow} />
        ))}
      </section>

      <section aria-labelledby="how-h" className="rounded-2xl border border-slate-200 bg-white p-6">
        <h2 id="how-h" className="text-lg font-semibold text-slate-900">How every run works</h2>
        <ol className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-3 lg:grid-cols-5">
          {["Intent", "Evidence", "Research", "Plan", "Policy", "Approval", "Action", "Verification", "Audit", "Memory"].map((s, i) => (
            <li key={s} className="rounded-lg bg-slate-50 px-3 py-2">
              <span className="mr-2 text-xs text-slate-500">{i + 1}</span>
              {s}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
