import { SafeText } from "./SafeText";

const MAX_DEPTH = 5;
const REDACTED = /^\[?\s*redacted\s*\]?$/i;

function Leaf({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-slate-400">null</span>;
  if (typeof value === "string") {
    if (REDACTED.test(value.trim())) {
      return (
        <span className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-xs text-slate-700" title="Redacted by the platform">
          {value}
        </span>
      );
    }
    return <SafeText text={value} />;
  }
  return <span className="font-mono text-sm">{String(value)}</span>;
}

/** Generic, safe renderer for redacted JSON payloads. Everything is rendered as text. */
export function PayloadView({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-slate-400">empty list</span>;
    if (depth >= MAX_DEPTH) return <span className="text-slate-400">[{value.length} items]</span>;
    return (
      <ul className="list-disc space-y-1 pl-5">
        {value.map((v, i) => (
          <li key={i}>
            <PayloadView value={v} depth={depth + 1} />
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object" && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-slate-400">empty</span>;
    if (depth >= MAX_DEPTH) return <span className="text-slate-400">{"{...}"}</span>;
    return (
      <dl className="grid grid-cols-[minmax(6rem,max-content)_1fr] gap-x-3 gap-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              <SafeText text={k} defang={false} />
            </dt>
            <dd className="min-w-0 text-sm text-slate-800">
              <PayloadView value={v} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <Leaf value={value} />;
}
