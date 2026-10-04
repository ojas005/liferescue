import type { WorkflowSummary } from "@/lib/api/schemas";

/**
 * Marketing copy for the three experiences, keyed by workflow_id. This is presentation only:
 * the API remains the source of truth for which workflows exist and what their intent schemas are.
 * It is the fallback when GET /api/workflows is unavailable or omits name/description.
 */
export type WorkflowMeta = {
  workflowId: string;
  product: string;
  tagline: string;
  description: string;
  highlights: string[];
  accent: "orange" | "violet" | "teal" | "slate";
};

export const WORKFLOW_CATALOG: Record<string, WorkflowMeta> = {
  vehicle_breakdown: {
    workflowId: "vehicle_breakdown",
    product: "LifeRescue",
    tagline: "Roadside and incident help, coordinated.",
    description:
      "Stuck on the road? Describe what happened and where. LifeRescue gathers evidence, plans the safest next steps and asks for your approval before anything is dispatched.",
    highlights: ["Breakdown and incident intake", "Safety-first plan", "You approve every dispatch"],
    accent: "orange",
  },
  scam_investigation: {
    workflowId: "scam_investigation",
    product: "ScamShield",
    tagline: "Check a suspicious message before you act.",
    description:
      "Paste a suspicious message, link or number. ScamShield treats it as untrusted data, researches it, and explains the risk with evidence you can inspect.",
    highlights: ["Suspicious message analysis", "Evidence you can inspect", "Nothing is opened or clicked for you"],
    accent: "violet",
  },
  life_admin: {
    workflowId: "life_admin",
    product: "LifeOS",
    tagline: "Life admin on autopilot, with you in control.",
    description:
      "Bills, renewals, bookings and paperwork. LifeOS turns a goal into a checked plan and only acts after you approve.",
    highlights: ["Goal to plan", "Policy-checked actions", "Verification and audit trail"],
    accent: "teal",
  },
};

export const CATALOG_ORDER = ["vehicle_breakdown", "scam_investigation", "life_admin"] as const;

export function metaFor(workflowId: string, workflow?: Pick<WorkflowSummary, "title" | "description">): WorkflowMeta {
  const known = WORKFLOW_CATALOG[workflowId];
  if (known) {
    return { ...known, description: workflow?.description?.trim() ? workflow.description : known.description };
  }
  return {
    workflowId,
    product: workflow?.title ?? workflowId,
    tagline: "Workflow on the LifeRescue runtime.",
    description: workflow?.description ?? "No description provided by the API.",
    highlights: [],
    accent: "slate",
  };
}

export type WorkflowEntry = {
  workflowId: string;
  meta: WorkflowMeta;
  /** The API workflow record, if the API returned it. */
  workflow?: WorkflowSummary;
};

/** Merge API workflows with the catalog: catalog order first, then any extra API workflows. */
export function mergeWorkflows(apiWorkflows: WorkflowSummary[] | undefined): WorkflowEntry[] {
  const byId = new Map((apiWorkflows ?? []).map((w) => [w.workflow_id, w]));
  const ids = [...CATALOG_ORDER, ...[...byId.keys()].filter((id) => !(CATALOG_ORDER as readonly string[]).includes(id))];
  return ids.map((id) => {
    const workflow = byId.get(id);
    return { workflowId: id, workflow, meta: metaFor(id, workflow) };
  });
}
