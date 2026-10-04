import type { TimelineEvent } from "@/lib/api/schemas";
import { summarizeEvidence } from "@/lib/run-view";
import { PayloadView } from "./PayloadView";
import { SafeText } from "./SafeText";

function Chips({ items, tone }: { items: string[]; tone: "ok" | "warn" | "neutral" }) {
  const cls = tone === "ok" ? "bg-emerald-50 text-emerald-900" : tone === "warn" ? "bg-amber-50 text-amber-900" : "bg-slate-100 text-slate-800";
  return (
    <ul className="mt-1 flex flex-wrap gap-1.5">
      {items.map((it, i) => (
        <li key={`${it}-${i}`} className={`rounded px-2 py-0.5 text-xs ${cls}`}>
          <SafeText text={it} />
        </li>
      ))}
    </ul>
  );
}

/**
 * Evidence + research as exposed by contract 0.1.0: keys collected/missing, research queries and source URLs
 * (defanged, never links), and the user's own submitted input (untrusted data).
 */
export function EvidencePanel({ events, input }: { events: TimelineEvent[]; input?: Record<string, unknown> }) {
  const ev = summarizeEvidence(events);
  const empty = ev.collected.length + ev.missing.length + ev.queries.length + ev.skipped.length + ev.sourceUrls.length + ev.other.length === 0;
  return (
    <section aria-labelledby="evidence-h" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 id="evidence-h" className="text-sm font-semibold text-slate-900">
        Evidence and research
      </h2>
      <p className="mt-0.5 text-xs text-slate-500">Shown as inert text. Links are defanged and are never opened, fetched or followed for you.</p>
      {input && Object.keys(input).length > 0 ? (
        <div className="mt-3" data-testid="submitted-input">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
            Your submitted input <span className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 normal-case text-amber-900">untrusted data</span>
          </h3>
          <div className="mt-1 rounded-lg border border-slate-200 bg-slate-50 p-2">
            <PayloadView value={input} />
          </div>
        </div>
      ) : null}
      {empty ? (
        <p className="mt-3 text-sm text-slate-600">No evidence gathered yet.</p>
      ) : (
        <div className="mt-3 space-y-3" data-testid="evidence-summary">
          {ev.collected.length > 0 ? (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Collected</h3>
              <Chips items={ev.collected} tone="ok" />
            </div>
          ) : null}
          {ev.missing.length > 0 ? (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Missing</h3>
              <Chips items={ev.missing} tone="warn" />
            </div>
          ) : null}
          {ev.queries.length > 0 ? (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Research queries</h3>
              <Chips items={ev.queries} tone="neutral" />
            </div>
          ) : null}
          {ev.skipped.length > 0 ? (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Skipped</h3>
              <Chips items={ev.skipped} tone="warn" />
            </div>
          ) : null}
          {ev.sourceUrls.length > 0 ? (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Source URLs (defanged)</h3>
              <ul className="mt-1 space-y-1 text-xs">
                {ev.sourceUrls.map((u, i) => (
                  <li key={`${u}-${i}`} data-testid="source-url">
                    <SafeText text={u} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {ev.other.map((o) => (
            <div key={o.key}>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Other {o.type} data</h3>
              <PayloadView value={o.payload} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
