/**
 * MOCK API fixtures. DEV/TEST ONLY.
 *
 * Built from the SHAPE of the frozen platform contract 0.1.0 (openapi.yaml + contract/fakes/engine.py event
 * payloads + contract/fixtures/vehicle_breakdown.py). They contain NO AI output and make NO claims about real
 * behaviour: every tool result is `mocked: true`, texts are fixtures, and the UI shows a "MOCK API" banner while
 * this module serves requests. The input schema of vehicle_breakdown is copied from the contract fixture; the
 * scam_investigation and life_admin schemas are INVENTED here (the contract defines no workflow other than the
 * vehicle_breakdown example) to exercise the generic form renderer.
 */
import type { EventType, RunState, WorkflowSummary } from "@/lib/api/schemas";

export const MOCK_WORKFLOWS: WorkflowSummary[] = [
  {
    workflow_id: "vehicle_breakdown",
    version: "0.1.0",
    title: "Vehicle breakdown",
    description: "Help a driver whose vehicle has broken down: gather facts, research options, plan, ask approval, act, verify.",
    input_schema: {
      type: "object",
      required: ["description"],
      properties: {
        description: { type: "string", minLength: 3, maxLength: 2000 },
        location: { type: "string", maxLength: 300 },
        vehicle: { type: "string", maxLength: 200 },
      },
      additionalProperties: false,
    },
  },
  {
    workflow_id: "scam_investigation",
    version: "0.1.0",
    title: "Scam investigation",
    description: "Investigate a suspicious message, link or call. The text is treated as untrusted data.",
    input_schema: {
      type: "object",
      required: ["message_text"],
      properties: {
        message_text: { type: "string", title: "Suspicious message", description: "Paste the full text. It is treated as data, never as instructions.", minLength: 3, maxLength: 5000 },
        channel: { type: "string", title: "Where did it arrive?", enum: ["sms", "email", "whatsapp", "phone_call", "other"] },
        suspicious_url: { type: "string", format: "uri", title: "Link in the message", description: "Shown as inert text only. It is never opened for you.", maxLength: 2048 },
        already_responded: { type: "boolean", title: "I already replied or paid" },
      },
      additionalProperties: false,
    },
  },
  {
    workflow_id: "life_admin",
    version: "0.1.0",
    title: "Life admin",
    description: "Plan and carry out a piece of life admin, with your approval before anything is committed.",
    input_schema: {
      type: "object",
      required: ["goal", "category"],
      properties: {
        goal: { type: "string", title: "What do you need done?", description: "For example: renew my car insurance before it lapses.", minLength: 3, maxLength: 2000 },
        category: { type: "string", title: "Category", enum: ["bills", "renewal", "booking", "paperwork"] },
        due_date: { type: "string", title: "Due date", format: "date", description: "YYYY-MM-DD, optional.", maxLength: 10 },
        budget: { type: "number", title: "Budget", minimum: 0 },
        details: { type: "object", title: "Extra details (JSON)", description: "Complex types fall back to a JSON field." },
      },
      additionalProperties: false,
    },
  },
];

export type Draft = { step: RunState; type: EventType; payload: Record<string, unknown> };

export type MockStep = { step_id: string; action_type: string; tool_name: string; params: Record<string, unknown>; rationale: string };

export type MockScript = {
  /** Events up to and including the pending approval request. */
  before: Draft[];
  steps: MockStep[];
  writeStepId: string;
  afterApprove: () => Draft[];
  afterDeny: () => Draft[];
};

const POLICY_VERSION = "mock-policy-0001";

type Content = {
  category: string;
  urgency: "low" | "medium" | "high" | "critical";
  summary: string;
  entities: Record<string, unknown>;
  collected: string[];
  missing: string[];
  queries: string[];
  sourceUrls: string[];
  planSummary: string;
  readStep: MockStep;
  writeStep: MockStep;
  writeRule: { rule_id: string; risk: "low" | "medium" | "high" | "critical"; reason: string };
};

const str = (v: unknown): string => (typeof v === "string" ? v : "");

function contentFor(workflowId: string, input: Record<string, unknown>): Content {
  switch (workflowId) {
    case "vehicle_breakdown":
      return {
        category: "vehicle_breakdown",
        urgency: "high",
        summary: "Mock fixture: vehicle breakdown reported",
        entities: { location: str(input["location"]) || null, vehicle: str(input["vehicle"]) || null },
        collected: ["description", ...(input["location"] ? ["location"] : []), ...(input["vehicle"] ? ["vehicle"] : [])],
        missing: [...(input["location"] ? [] : ["location"])],
        queries: ["roadside assistance near {location}"],
        sourceUrls: ["https://roadside.example/mock-directory"],
        planSummary: "Look up roadside options, then request a tow (needs your approval).",
        readStep: { step_id: "s1", action_type: "lookup", tool_name: "web_search", params: { query: "roadside assistance near {location}" }, rationale: "Find nearby roadside operators." },
        writeStep: { step_id: "s2", action_type: "request_tow", tool_name: "dispatch_tow", params: { location: str(input["location"]) || "unknown", vehicle: str(input["vehicle"]) || "unknown" }, rationale: "Send a tow to the reported location." },
        writeRule: { rule_id: "tow-needs-approval", risk: "high", reason: "Dispatching a tow commits the user; the user must approve." },
      };
    case "scam_investigation":
      return {
        category: "scam_investigation",
        urgency: "medium",
        summary: "Mock fixture: suspicious message received",
        entities: { channel: str(input["channel"]) || null, message_excerpt: str(input["message_text"]).slice(0, 200), url: str(input["suspicious_url"]) || null },
        collected: ["message_text", ...(input["channel"] ? ["channel"] : []), ...(input["suspicious_url"] ? ["suspicious_url"] : [])],
        missing: [],
        queries: ["reports of scam messages matching this pattern"],
        sourceUrls: input["suspicious_url"] ? [str(input["suspicious_url"])] : [],
        planSummary: "Assess the message against known patterns, then draft a report (needs your approval).",
        readStep: { step_id: "s1", action_type: "lookup", tool_name: "web_search", params: { query: "reports of scam messages matching this pattern" }, rationale: "Compare against known scam patterns." },
        writeStep: { step_id: "s2", action_type: "report_scam", tool_name: "send_message", params: { destination: "platform_abuse_desk" }, rationale: "Report the message to the platform." },
        writeRule: { rule_id: "message-needs-approval", risk: "medium", reason: "Messages leave the system; the user must approve." },
      };
    default:
      return {
        category: workflowId,
        urgency: "low",
        summary: "Mock fixture: life admin request",
        entities: { category: str(input["category"]) || null, goal: str(input["goal"]).slice(0, 200) },
        collected: ["goal", "category", ...(input["due_date"] ? ["due_date"] : [])],
        missing: [...(input["due_date"] ? [] : ["due_date"])],
        queries: ["provider options for {category}"],
        sourceUrls: [],
        planSummary: "Check provider options, then submit the request (needs your approval).",
        readStep: { step_id: "s1", action_type: "lookup", tool_name: "web_search", params: { query: "provider options for {category}" }, rationale: "Check options." },
        writeStep: { step_id: "s2", action_type: "submit", tool_name: "submit_request", params: { category: str(input["category"]) || "unknown" }, rationale: "Submit the request on your behalf." },
        writeRule: { rule_id: "submit-needs-approval", risk: "medium", reason: "Submitting may commit money; the user must approve." },
      };
  }
}

const change = (from: RunState | null, to: RunState, extra: Record<string, unknown> = {}): Draft => ({
  step: to,
  type: "state_change",
  payload: { ...(from ? { from } : {}), to, ...extra },
});

export function buildScript(workflowId: string, input: Record<string, unknown>, approvalId: string): MockScript {
  const c = contentFor(workflowId, input);
  const steps = [c.readStep, c.writeStep];
  const before: Draft[] = [
    change(null, "intent", { note: "run created (MOCK)" }),
    { step: "intent", type: "intent", payload: { summary: c.summary, category: c.category, urgency: c.urgency, entities: c.entities, model: "mock-model", adapter: "mock" } },
    change("intent", "evidence"),
    { step: "evidence", type: "evidence", payload: { collected: c.collected, missing: c.missing } },
    change("evidence", "research"),
    { step: "research", type: "research", payload: { queries: c.queries, skipped: [], source_urls: c.sourceUrls } },
    change("research", "plan"),
    { step: "plan", type: "plan", payload: { summary: c.planSummary, steps } },
    change("plan", "policy"),
    { step: "policy", type: "policy", payload: { step_id: c.readStep.step_id, tool: c.readStep.tool_name, outcome: "allow", risk: "low", rule_id: "read-ok", reason: "Read-only tools are allowed.", policy_version: POLICY_VERSION } },
    { step: "policy", type: "policy", payload: { step_id: c.writeStep.step_id, tool: c.writeStep.tool_name, outcome: "needs_approval", risk: c.writeRule.risk, rule_id: c.writeRule.rule_id, reason: c.writeRule.reason, policy_version: POLICY_VERSION } },
    change("policy", "approval"),
    // expires_at is added by the engine (it knows the schedule).
    { step: "approval", type: "approval", payload: { approval_id: approvalId, step_id: c.writeStep.step_id, status: "pending", summary: `${c.writeStep.action_type}: ${c.writeStep.tool_name} ${JSON.stringify(c.writeStep.params)}`.slice(0, 300) } },
  ];
  const actionPayload = (s: MockStep, output: Record<string, unknown>): Record<string, unknown> => ({
    step_id: s.step_id,
    tool: s.tool_name,
    status: "ok",
    mocked: true,
    output,
    error: null,
  });
  return {
    before,
    steps,
    writeStepId: c.writeStep.step_id,
    afterApprove: () => [
      { step: "approval", type: "approval", payload: { approval_id: approvalId, step_id: c.writeStep.step_id, status: "approved" } },
      change("approval", "action"),
      { step: "action", type: "action", payload: actionPayload(c.readStep, { note: "MOCK FIXTURE: no real search was performed", results: 2 }) },
      { step: "action", type: "action", payload: actionPayload(c.writeStep, { note: "MOCK FIXTURE: nothing was sent, booked or dispatched", reference: "MOCK-0001" }) },
      change("action", "verification"),
      { step: "verification", type: "verification", payload: { passed: true, checks: [{ check_id: "write-tool-ok", passed: true, detail: "tool_result_status ok (mock)" }, { check_id: "has-evidence", passed: true, detail: "evidence present" }] } },
      change("verification", "audit"),
      { step: "audit", type: "audit", payload: { audit_records: 6, chain_head_before_summary: "mock-chain-head" } },
      change("audit", "completed"),
    ],
    afterDeny: () => [
      { step: "approval", type: "approval", payload: { approval_id: approvalId, step_id: c.writeStep.step_id, status: "denied" } },
      change("approval", "denied", { reason: `approval for ${c.writeStep.step_id} was denied` }),
    ],
  };
}

export { POLICY_VERSION };
