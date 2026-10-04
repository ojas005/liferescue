/**
 * Runtime (zod) schemas for the LifeRescue Run API, contract 0.1.0 (apps/web/contract/openapi.yaml, a verbatim
 * copy of packages/contract/openapi.yaml owned by LR 03).
 *
 * TypeScript types for requests/responses come from the GENERATED file (generated/openapi.d.ts, `npm run gen:api`).
 * These zod schemas are the runtime guard at the network boundary. Each schema is checked at compile time to
 * produce a value assignable to the generated type (see "conformance" at the bottom), so drift between the
 * runtime guard and the spec fails `npm run typecheck`.
 *
 * Parsing is deliberately tolerant of ADDITIVE changes (looseObject: unknown extra keys are kept, not rejected),
 * because contract minor/patch versions are additive-only. Enums are strict: a new state/event type is a breaking
 * change per CONTRACT-README section 3 and should fail loudly as a "contract mismatch".
 */
import { z } from "zod";
import type { components } from "./generated/openapi";

type Schemas = components["schemas"];

export const CONTRACT_VERSION = "0.1.0";

/* ------------------------------------------------------------------- enums */

export const RUN_STATES = [
  "intent",
  "evidence",
  "research",
  "plan",
  "policy",
  "approval",
  "action",
  "verification",
  "audit",
  "completed",
  "failed",
  "denied",
  "cancelled",
] as const;
export const RunStateSchema = z.enum(RUN_STATES);
export type RunState = z.infer<typeof RunStateSchema>;

export const TERMINAL_STATES: readonly RunState[] = ["completed", "failed", "denied", "cancelled"];
export function isTerminalState(state: RunState): boolean {
  return TERMINAL_STATES.includes(state);
}

/** CONTRACT: cancel is allowed only before ACTION starts (and not once terminal). */
const CANCELLABLE: readonly RunState[] = ["intent", "evidence", "research", "plan", "policy", "approval"];
export function canCancel(state: RunState): boolean {
  return CANCELLABLE.includes(state);
}

export const EVENT_TYPES = [
  "intent",
  "evidence",
  "research",
  "plan",
  "policy",
  "approval",
  "action",
  "verification",
  "audit",
  "state_change",
  "error",
] as const;
export const EventTypeSchema = z.enum(EVENT_TYPES);
export type EventType = z.infer<typeof EventTypeSchema>;

export function isKnownEventType(value: string): value is EventType {
  return (EVENT_TYPES as readonly string[]).includes(value);
}

export const RiskLevelSchema = z.enum(["low", "medium", "high", "critical"]);
export const PolicyOutcomeSchema = z.enum(["allow", "needs_approval", "deny"]);
export const ApprovalStatusSchema = z.enum(["pending", "approved", "denied", "expired", "consumed", "revoked"]);
export type ApprovalStatus = z.infer<typeof ApprovalStatusSchema>;

export const APPROVAL_DECISIONS = ["approve", "deny"] as const;
export type ApprovalDecision = (typeof APPROVAL_DECISIONS)[number];

/* ----------------------------------------------------------------- objects */

const jsonObject = z.record(z.string(), z.unknown());

export const WorkflowSummarySchema = z.looseObject({
  workflow_id: z.string().min(1),
  version: z.string(),
  title: z.string(),
  description: z.string(),
  input_schema: jsonObject,
});
export type WorkflowSummary = z.infer<typeof WorkflowSummarySchema>;
export const WorkflowListSchema = z.array(WorkflowSummarySchema);

export const IntentResultSchema = z.looseObject({
  summary: z.string(),
  category: z.string(),
  urgency: RiskLevelSchema.default("low"),
  entities: jsonObject.default({}),
  missing_fields: z.array(z.string()).default([]),
});

export const PlanStepSchema = z.looseObject({
  step_id: z.string(),
  action_type: z.string(),
  tool_name: z.string(),
  params: jsonObject.default({}),
  rationale: z.string(),
});
export type PlanStep = z.infer<typeof PlanStepSchema>;

export const PolicyDecisionSchema = z.looseObject({
  step_id: z.string(),
  outcome: PolicyOutcomeSchema,
  risk: RiskLevelSchema,
  rule_id: z.string(),
  reason: z.string(),
  policy_version: z.string(),
  action_digest: z.string(),
});
export type PolicyDecision = z.infer<typeof PolicyDecisionSchema>;

export const ToolResultSchema = z.looseObject({
  tool_name: z.string(),
  status: z.enum(["ok", "error"]),
  output: jsonObject.default({}),
  mocked: z.boolean().default(false),
  error: z.string().nullable().default(null),
  action_digest: z.string().nullable().default(null),
});
export type ToolResult = z.infer<typeof ToolResultSchema>;

export const CheckResultSchema = z.looseObject({ check_id: z.string(), passed: z.boolean(), detail: z.string() });
export const VerificationResultSchema = z.looseObject({ passed: z.boolean(), checks: z.array(CheckResultSchema) });
export type VerificationResult = z.infer<typeof VerificationResultSchema>;

export const RunRecordSchema = z.looseObject({
  run_id: z.string(),
  workflow_id: z.string(),
  workflow_version: z.string(),
  contract_version: z.string(),
  owner: z.string().default("demo-user"),
  state: RunStateSchema.default("intent"),
  input: jsonObject,
  intent: IntentResultSchema.nullable().default(null),
  plan: z.array(PlanStepSchema).default([]),
  decisions: z.array(PolicyDecisionSchema).default([]),
  results: z.array(ToolResultSchema).default([]),
  verification: VerificationResultSchema.nullable().default(null),
  terminal_reason: z.string().nullable().default(null),
  version: z.number().int().default(0),
  created_at: z.string(),
  updated_at: z.string(),
});
export type RunRecord = z.infer<typeof RunRecordSchema>;

export const ApprovalSchema = z.looseObject({
  approval_id: z.string(),
  run_id: z.string(),
  step_id: z.string(),
  bound_digest: z.string(),
  status: ApprovalStatusSchema.default("pending"),
  risk: RiskLevelSchema,
  summary: z.string(),
  policy_version: z.string(),
  requested_at: z.string(),
  expires_at: z.string(),
  decided_by: z.string().nullable().default(null),
  decided_at: z.string().nullable().default(null),
  reason: z.string().nullable().default(null),
});
export type Approval = z.infer<typeof ApprovalSchema>;

export const RunResponseSchema = z.looseObject({
  run: RunRecordSchema,
  approvals: z.array(ApprovalSchema).default([]),
  last_seq: z.number().int().default(0),
});
export type RunResponse = z.infer<typeof RunResponseSchema>;

export const TimelineEventSchema = z.looseObject({
  event_id: z.string(),
  run_id: z.string(),
  seq: z.number().int(),
  ts: z.string(),
  step: RunStateSchema,
  type: EventTypeSchema,
  // Redacted by the platform before it reaches us; still treated as untrusted data when rendering.
  payload: jsonObject.default({}),
});
export type TimelineEvent = z.infer<typeof TimelineEventSchema>;

export const TimelinePageSchema = z.looseObject({
  run_id: z.string(),
  events: z.array(TimelineEventSchema),
  next_seq: z.number().int(),
  terminal: z.boolean(),
});
export type TimelinePage = z.infer<typeof TimelinePageSchema>;

export const ErrorResponseSchema = z.looseObject({ error: z.string(), message: z.string() });
export type ErrorResponse = z.infer<typeof ErrorResponseSchema>;

export const HealthResponseSchema = z.looseObject({
  status: z.literal("ok"),
  contract_version: z.string(),
  model_adapter: z.enum(["nebius", "mock"]),
});
export type HealthResponse = z.infer<typeof HealthResponseSchema>;

/* ---------------------------------------------------------------- requests */

export type CreateRunRequest = Schemas["CreateRunRequest"];
export type ApprovalDecisionRequest = Schemas["ApprovalDecisionRequest"];
export type CancelRunRequest = Schemas["CancelRunRequest"];

/* ------------------------------------------------------------- conformance */
// Compile-time only: each parsed shape must be assignable to the generated spec type. If the spec changes and
// `npm run gen:api` is re-run, a mismatch fails `npm run typecheck`.
type Conforms<Parsed extends Spec, Spec> = Parsed;
export type _Conformance = [
  Conforms<WorkflowSummary, Schemas["WorkflowSummary"]>,
  Conforms<RunResponse, Schemas["RunResponse"]>,
  Conforms<TimelinePage, Schemas["TimelinePage"]>,
  Conforms<Approval, Schemas["Approval"]>,
  Conforms<ErrorResponse, Schemas["ErrorResponse"]>,
  Conforms<HealthResponse, Schemas["HealthResponse"]>,
];

/* ----------------------------------------------------------------- helpers */

export function pendingApprovals(run: RunResponse | undefined): Approval[] {
  return (run?.approvals ?? []).filter((a) => a.status === "pending");
}

/** A tool result / action payload flagged `mocked: true` is a SIMULATED action (SECURITY T6). */
export function isSimulated(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  if (v["mocked"] === true) return true;
  const nested = v["result"];
  return typeof nested === "object" && nested !== null && (nested as Record<string, unknown>)["mocked"] === true;
}
