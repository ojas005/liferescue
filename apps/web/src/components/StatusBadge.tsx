const OK = "bg-emerald-50 text-emerald-800 ring-emerald-300";
const BAD = "bg-rose-50 text-rose-800 ring-rose-300";
const STYLES: Record<string, string> = {
  intent: "bg-blue-50 text-blue-800 ring-blue-300",
  evidence: "bg-blue-50 text-blue-800 ring-blue-300",
  research: "bg-blue-50 text-blue-800 ring-blue-300",
  plan: "bg-blue-50 text-blue-800 ring-blue-300",
  policy: "bg-blue-50 text-blue-800 ring-blue-300",
  approval: "bg-amber-50 text-amber-900 ring-amber-400",
  action: "bg-blue-50 text-blue-800 ring-blue-300",
  verification: "bg-blue-50 text-blue-800 ring-blue-300",
  audit: "bg-blue-50 text-blue-800 ring-blue-300",
  completed: OK,
  failed: BAD,
  denied: BAD,
  cancelled: "bg-slate-100 text-slate-700 ring-slate-300",
  // approval statuses
  pending: "bg-amber-50 text-amber-900 ring-amber-400",
  approved: OK,
  consumed: OK,
  expired: "bg-slate-100 text-slate-700 ring-slate-300",
  revoked: "bg-slate-100 text-slate-700 ring-slate-300",
};

const LABELS: Record<string, string> = {
  approval: "Awaiting approval",
  intent: "Understanding request",
  evidence: "Gathering evidence",
  research: "Researching",
  plan: "Planning",
  policy: "Checking policy",
  action: "Acting",
  verification: "Verifying",
  audit: "Auditing",
};

export function statusLabel(status: string, kind: "run" | "plain" = "plain"): string {
  if (kind === "run" && LABELS[status]) return LABELS[status]!;
  const s = status.replace(/[_-]+/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "Unknown";
}

/** `kind="run"` shows pipeline-stage wording for in-flight RunState values; terminal states read as-is. */
export function StatusBadge({ status, kind = "run" }: { status: string; kind?: "run" | "plain" }) {
  const style = STYLES[status.toLowerCase()] ?? "bg-slate-100 text-slate-700 ring-slate-300";
  return (
    <span
      data-testid="status-badge"
      data-status={status}
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${style}`}
    >
      {statusLabel(status, kind)}
    </span>
  );
}
