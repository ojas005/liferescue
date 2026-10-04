import Link from "next/link";
import type { WorkflowMeta } from "@/lib/workflows/catalog";

const ACCENTS: Record<WorkflowMeta["accent"], { bar: string; chip: string; btn: string }> = {
  orange: { bar: "bg-orange-500", chip: "bg-orange-50 text-orange-900", btn: "bg-orange-600 hover:bg-orange-700" },
  violet: { bar: "bg-violet-500", chip: "bg-violet-50 text-violet-900", btn: "bg-violet-600 hover:bg-violet-700" },
  teal: { bar: "bg-teal-500", chip: "bg-teal-50 text-teal-900", btn: "bg-teal-600 hover:bg-teal-700" },
  slate: { bar: "bg-slate-500", chip: "bg-slate-100 text-slate-800", btn: "bg-slate-700 hover:bg-slate-800" },
};

export function WorkflowCard({ meta, available = true }: { meta: WorkflowMeta; available?: boolean }) {
  const a = ACCENTS[meta.accent];
  return (
    <article data-testid="workflow-card" data-workflow-id={meta.workflowId} className="flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className={`h-1.5 ${a.bar}`} />
      <div className="flex flex-1 flex-col p-5">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-xl font-bold text-slate-900">{meta.product}</h3>
          <code className={`rounded px-2 py-0.5 text-xs ${a.chip}`}>{meta.workflowId}</code>
        </div>
        <p className="mt-1 text-sm font-medium text-slate-700">{meta.tagline}</p>
        <p className="mt-3 text-sm text-slate-600">{meta.description}</p>
        {meta.highlights.length > 0 ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600">
            {meta.highlights.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        ) : null}
        <div className="mt-auto pt-5">
          <Link
            href={`/workflows/${encodeURIComponent(meta.workflowId)}`}
            className={`inline-flex items-center rounded-lg px-4 py-2 text-sm font-semibold text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 ${a.btn}`}
          >
            Start with {meta.product}
          </Link>
          {!available ? <p className="mt-2 text-xs text-slate-500">Not reported by the API right now; the form may be unavailable.</p> : null}
        </div>
      </div>
    </article>
  );
}
