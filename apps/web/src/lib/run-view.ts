/** Pure helpers that turn timeline events / run snapshots into view models for the shared components. */
import type { RunResponse, TimelineEvent } from "@/lib/api/schemas";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

export type EvidenceSummary = {
  /** Evidence keys the runtime collected / could not collect (contract: evidence event payload). */
  collected: string[];
  missing: string[];
  queries: string[];
  skipped: string[];
  sourceUrls: string[];
  /** Any evidence/research event whose payload did not match the expected shape is kept for generic rendering. */
  other: { key: string; type: string; payload: Obj }[];
};

/**
 * ASSUMPTION (contract 0.1.0): the API exposes evidence only as event payloads
 *   evidence: {collected: string[], missing: string[]}
 *   research: {queries: string[], skipped: string[], source_urls: string[]}
 * There is no endpoint that returns evidence VALUES; the user's own input is available as RunRecord.input.
 */
export function summarizeEvidence(events: TimelineEvent[]): EvidenceSummary {
  const out: EvidenceSummary = { collected: [], missing: [], queries: [], skipped: [], sourceUrls: [], other: [] };
  for (const e of events) {
    if (e.type !== "evidence" && e.type !== "research") continue;
    const p = e.payload;
    const known = e.type === "evidence" ? ["collected", "missing"] : ["queries", "skipped", "source_urls"];
    if (e.type === "evidence") {
      out.collected.push(...strs(p["collected"]));
      out.missing.push(...strs(p["missing"]));
    } else {
      out.queries.push(...strs(p["queries"]));
      out.skipped.push(...strs(p["skipped"]));
      out.sourceUrls.push(...strs(p["source_urls"]));
    }
    const rest = Object.fromEntries(Object.entries(p).filter(([k]) => !known.includes(k)));
    if (Object.keys(rest).length > 0) out.other.push({ key: e.event_id, type: e.type, payload: rest });
  }
  return out;
}

export type PlanRow = {
  stepId: string;
  actionType: string;
  toolName: string;
  rationale: string;
  params: Obj;
  outcome?: string;
  risk?: string;
  ruleId?: string;
  reason?: string;
};

/** Plan steps from RunRecord.plan joined with RunRecord.decisions (by step_id). */
export function planRows(snapshot: RunResponse | undefined): PlanRow[] {
  if (!snapshot) return [];
  const decisions = new Map(snapshot.run.decisions.map((d) => [d.step_id, d]));
  return snapshot.run.plan.map((s) => {
    const d = decisions.get(s.step_id);
    return {
      stepId: s.step_id,
      actionType: s.action_type,
      toolName: s.tool_name,
      rationale: s.rationale,
      params: s.params,
      outcome: d?.outcome,
      risk: d?.risk,
      ruleId: d?.rule_id,
      reason: d?.reason,
    };
  });
}

export { isObj };
