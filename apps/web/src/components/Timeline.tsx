import type { TimelineEvent as TimelineEventData } from "@/lib/api/schemas";
import { TimelineEvent } from "./TimelineEvent";

export function Timeline({ events, live = false }: { events: TimelineEventData[]; live?: boolean }) {
  if (events.length === 0) {
    return (
      <p className="text-sm text-slate-600" role="status">
        {live ? "Waiting for the first event..." : "No events yet."}
      </p>
    );
  }
  return (
    <ol aria-label="Run timeline" className="relative ml-1.5 space-y-5 border-l border-slate-200">
      {events.map((e) => (
        <TimelineEvent key={e.event_id} event={e} />
      ))}
      {live ? (
        <li className="pl-8 text-xs text-slate-500" role="status">
          Updating live...
        </li>
      ) : null}
    </ol>
  );
}
