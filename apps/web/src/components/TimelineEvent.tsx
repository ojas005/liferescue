import { isKnownEventType, isSimulated, type TimelineEvent as TimelineEventData } from "@/lib/api/schemas";
import { PayloadView } from "./PayloadView";
import { SafeText } from "./SafeText";

export const EVENT_STYLES: Record<string, { label: string; dot: string; chip: string }> = {
  intent: { label: "Intent", dot: "bg-indigo-500", chip: "bg-indigo-50 text-indigo-800" },
  evidence: { label: "Evidence", dot: "bg-sky-500", chip: "bg-sky-50 text-sky-800" },
  research: { label: "Research", dot: "bg-cyan-500", chip: "bg-cyan-50 text-cyan-800" },
  plan: { label: "Plan", dot: "bg-violet-500", chip: "bg-violet-50 text-violet-800" },
  policy: { label: "Policy", dot: "bg-fuchsia-500", chip: "bg-fuchsia-50 text-fuchsia-800" },
  approval: { label: "Approval", dot: "bg-amber-500", chip: "bg-amber-50 text-amber-900" },
  action: { label: "Action", dot: "bg-orange-500", chip: "bg-orange-50 text-orange-900" },
  verification: { label: "Verification", dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-800" },
  audit: { label: "Audit", dot: "bg-slate-500", chip: "bg-slate-100 text-slate-800" },
  state_change: { label: "State", dot: "bg-slate-400", chip: "bg-slate-100 text-slate-700" },
  error: { label: "Error", dot: "bg-rose-500", chip: "bg-rose-50 text-rose-800" },
};
const FALLBACK = { dot: "bg-slate-400", chip: "bg-slate-100 text-slate-700" };

function formatTime(ts: string | undefined): string | undefined {
  if (!ts) return undefined;
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString();
}

/** One-line human summary derived from the (redacted) payload. Contract events carry no summary field. */
export function eventHeadline(e: TimelineEventData): string | undefined {
  const p = e.payload;
  const s = (k: string): string | undefined => (typeof p[k] === "string" ? (p[k] as string) : undefined);
  switch (e.type) {
    case "state_change":
      return s("from") ? `${s("from")} \u2192 ${s("to")}` : `started at ${s("to") ?? e.step}`;
    case "intent":
    case "plan":
      return s("summary");
    case "policy":
      return s("step_id") ? `${s("step_id")} (${s("tool") ?? "tool"}): ${s("outcome") ?? "?"} \u2013 ${s("reason") ?? ""}` : undefined;
    case "approval":
      return s("approval_id") ? `approval ${s("approval_id")} for ${s("step_id") ?? "step"}: ${s("status") ?? "pending"}` : undefined;
    case "action":
      return `${s("tool") ?? "tool"} (${s("step_id") ?? "step"}): ${s("status") ?? "?"}`;
    case "verification":
      return p["passed"] === true ? "verification passed" : p["passed"] === false ? "verification failed" : undefined;
    case "error":
      return s("reason");
    default:
      return undefined;
  }
}

export function TimelineEvent({ event }: { event: TimelineEventData }) {
  const known = isKnownEventType(event.type);
  const style = known ? EVENT_STYLES[event.type]! : { ...FALLBACK, label: event.type };
  const time = formatTime(event.ts);
  const hasPayload = Object.keys(event.payload).length > 0;
  const headline = eventHeadline(event);
  const simulated = isSimulated(event.payload);
  return (
    <li data-testid="timeline-event" data-event-type={event.type} data-seq={event.seq} className="relative pl-8">
      <span aria-hidden className={`absolute -left-[7px] top-1.5 h-3 w-3 rounded-full ring-4 ring-white ${style.dot}`} />
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${style.chip}`}>
          <SafeText text={style.label} defang={false} />
        </span>
        <span className="text-xs text-slate-600" title="Pipeline step">
          step: <span data-testid="event-step">{event.step}</span>
        </span>
        <span className="text-xs text-slate-400">#{event.seq}</span>
        {time ? <time className="text-xs text-slate-500">{time}</time> : null}
        {simulated ? (
          <span data-testid="simulated-badge" className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-bold uppercase text-amber-900" title="This action was simulated; nothing real happened">
            simulated
          </span>
        ) : null}
        {!known ? <span className="text-xs text-slate-500">(unrecognised event type)</span> : null}
      </div>
      {headline ? (
        <p className="mt-1 text-sm font-medium text-slate-900">
          <SafeText text={headline} />
        </p>
      ) : null}
      {hasPayload ? (
        <details className="mt-1 rounded-md border border-slate-200 bg-slate-50 p-2 text-sm">
          <summary className="cursor-pointer text-xs font-medium text-slate-600">Details (redacted payload)</summary>
          <div className="mt-2">
            <PayloadView value={event.payload} />
          </div>
        </details>
      ) : null}
    </li>
  );
}
