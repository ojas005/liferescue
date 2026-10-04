/**
 * In-memory MOCK run engine (DEV/TEST ONLY) that serves the frozen contract 0.1.0 shapes:
 * GET /api/workflows, POST /api/runs, GET /api/runs/{id}, GET /api/runs/{id}/timeline?after_seq=,
 * POST /api/runs/{id}/approvals/{approval_id}, POST /api/runs/{id}/cancel, GET /api/health.
 * A run advances through the pipeline over time and PAUSES at APPROVAL until decided. State is in server
 * memory only (lost on restart). It is a fixture of the API contract, not product behaviour.
 */
import { createHash, randomUUID } from "node:crypto";
import {
  canCancel,
  CONTRACT_VERSION,
  isTerminalState,
  RunStateSchema,
  type Approval,
  type ApprovalDecision,
  type ErrorResponse,
  type RunRecord,
  type RunResponse,
  type RunState,
  type TimelineEvent,
  type TimelinePage,
} from "@/lib/api/schemas";
import { buildScript, MOCK_WORKFLOWS, POLICY_VERSION, type Draft, type MockScript } from "./fixtures";

export type MockRun = {
  id: string;
  workflowId: string;
  workflowVersion: string;
  input: Record<string, unknown>;
  createdAt: number;
  script: MockScript;
  approvalId: string;
  decision?: { value: ApprovalDecision; at: number; reason: string | null };
  cancel?: { at: number; reason: string | null };
};

export type MockStore = { runs: Map<string, MockRun>; newId: () => string };

export function newStore(newId: () => string = () => randomUUID()): MockStore {
  return { runs: new Map(), newId };
}

const g = globalThis as unknown as { __lrMockStore?: MockStore };
export function sharedStore(): MockStore {
  g.__lrMockStore ??= newStore();
  return g.__lrMockStore;
}

export type EngineOptions = { stepMs: number; now: number };
export const DEFAULT_STEP_MS = 700;
const APPROVAL_TTL_MS = 900_000;

type Scheduled = { at: number; draft: Draft };

function schedule(run: MockRun, stepMs: number): Scheduled[] {
  const out: Scheduled[] = run.script.before.map((draft, i) => {
    const at = run.createdAt + i * stepMs;
    const d = draft.type === "approval" ? { ...draft, payload: { ...draft.payload, expires_at: new Date(at + APPROVAL_TTL_MS).toISOString() } } : draft;
    return { draft: d, at };
  });
  if (run.cancel) {
    const kept = out.filter((s) => s.at <= run.cancel!.at);
    kept.push({
      at: run.cancel.at,
      draft: { step: "cancelled", type: "state_change", payload: { from: lastState(kept), to: "cancelled", reason: run.cancel.reason ?? "cancelled by user" } },
    });
    return kept;
  }
  if (run.decision) {
    const after = run.decision.value === "approve" ? run.script.afterApprove() : run.script.afterDeny();
    after.forEach((draft, i) => out.push({ draft, at: run.decision!.at + i * stepMs }));
  }
  return out;
}

function lastState(items: Scheduled[]): RunState {
  let s: RunState = "intent";
  for (const it of items) if (it.draft.type === "state_change") s = RunStateSchema.parse(it.draft.payload["to"]);
  return s;
}

function eventsFor(run: MockRun, opts: EngineOptions): TimelineEvent[] {
  return schedule(run, opts.stepMs)
    .map((s, i) => ({ s, seq: i + 1 }))
    .filter(({ s }) => s.at <= opts.now)
    .map(({ s, seq }) => ({
      event_id: `${run.id}-${seq}`,
      run_id: run.id,
      seq,
      ts: new Date(s.at).toISOString(),
      step: s.draft.step,
      type: s.draft.type,
      payload: s.draft.payload,
    }));
}

function digest(run: MockRun): string {
  return createHash("sha256").update(JSON.stringify({ run: run.id, tool: run.script.steps.at(-1)?.tool_name, params: run.script.steps.at(-1)?.params })).digest("hex");
}

/** Fold the visible events into the RunRecord, the same way a real store would have persisted them. */
function snapshot(run: MockRun, opts: EngineOptions): RunResponse {
  const events = eventsFor(run, opts);
  const rec: RunRecord = {
    run_id: run.id,
    workflow_id: run.workflowId,
    workflow_version: run.workflowVersion,
    contract_version: CONTRACT_VERSION,
    owner: "demo-user",
    state: "intent",
    input: run.input,
    intent: null,
    plan: [],
    decisions: [],
    results: [],
    verification: null,
    terminal_reason: null,
    version: events.length,
    created_at: new Date(run.createdAt).toISOString(),
    updated_at: new Date(events.at(-1)?.ts ?? run.createdAt).toISOString(),
  };
  let approvalStatus: Approval["status"] | undefined;
  let approvalVisible = false;
  for (const e of events) {
    const p = e.payload;
    switch (e.type) {
      case "state_change":
        rec.state = RunStateSchema.parse(p["to"]);
        if (typeof p["reason"] === "string") rec.terminal_reason = p["reason"];
        break;
      case "intent":
        rec.intent = { summary: String(p["summary"]), category: String(p["category"]), urgency: p["urgency"] as "low", entities: p["entities"] as Record<string, unknown>, missing_fields: [] };
        break;
      case "plan":
        rec.plan = p["steps"] as RunRecord["plan"];
        break;
      case "policy":
        rec.decisions.push({
          step_id: String(p["step_id"]),
          outcome: p["outcome"] as "allow",
          risk: p["risk"] as "low",
          rule_id: String(p["rule_id"]),
          reason: String(p["reason"]),
          policy_version: String(p["policy_version"]),
          action_digest: digest(run),
        });
        break;
      case "approval":
        approvalVisible = true;
        approvalStatus = (p["status"] as Approval["status"]) ?? "pending";
        break;
      case "action":
        if (approvalStatus === "approved") approvalStatus = "consumed";
        rec.results.push({
          tool_name: String(p["tool"]),
          status: p["status"] === "error" ? "error" : "ok",
          output: (p["output"] as Record<string, unknown>) ?? {},
          mocked: p["mocked"] === true,
          error: typeof p["error"] === "string" ? p["error"] : null,
          action_digest: null,
        });
        break;
      case "verification":
        rec.verification = { passed: p["passed"] === true, checks: p["checks"] as { check_id: string; passed: boolean; detail: string }[] };
        break;
      default:
        break;
    }
  }
  const approvals: Approval[] = [];
  if (approvalVisible) {
    const requestedAt = run.createdAt + (run.script.before.length - 1) * opts.stepMs;
    const cancelled = run.cancel !== undefined;
    approvals.push({
      approval_id: run.approvalId,
      run_id: run.id,
      step_id: run.script.writeStepId,
      bound_digest: digest(run),
      status: cancelled ? "revoked" : (approvalStatus ?? "pending"),
      risk: rec.decisions.find((d) => d.step_id === run.script.writeStepId)?.risk ?? "medium",
      summary: `${run.script.steps.at(-1)?.action_type}: ${run.script.steps.at(-1)?.tool_name} ${JSON.stringify(run.script.steps.at(-1)?.params)}`.slice(0, 300),
      policy_version: POLICY_VERSION,
      requested_at: new Date(requestedAt).toISOString(),
      expires_at: new Date(requestedAt + APPROVAL_TTL_MS).toISOString(),
      decided_by: run.decision ? "demo-user" : null,
      decided_at: run.decision ? new Date(run.decision.at).toISOString() : null,
      reason: run.decision?.reason ?? null,
    });
  }
  return { run: rec, approvals, last_seq: events.at(-1)?.seq ?? 0 };
}

export type MockResponse = { status: number; body: unknown };
const ok = (status: number, body: unknown): MockResponse => ({ status, body });
const err = (status: number, error: string, message: string): MockResponse => ({ status, body: { error, message } satisfies ErrorResponse });

/* ------- minimal JSON-schema subset validator (never echoes submitted values: SECURITY A5) ------- */
function validateInput(schema: Record<string, unknown>, input: unknown): string | undefined {
  if (typeof input !== "object" || input === null || Array.isArray(input)) return "input must be an object";
  const obj = input as Record<string, unknown>;
  const props = (schema["properties"] ?? {}) as Record<string, Record<string, unknown>>;
  for (const key of (schema["required"] as string[] | undefined) ?? []) {
    if (obj[key] === undefined || obj[key] === null || obj[key] === "") return `input.${key} is required`;
  }
  for (const [key, value] of Object.entries(obj)) {
    const def = props[key];
    if (!def) return schema["additionalProperties"] === false ? `input.${key} is not allowed` : undefined;
    const t = def["type"];
    if (t === "string" && typeof value !== "string") return `input.${key} must be a string`;
    if (t === "boolean" && typeof value !== "boolean") return `input.${key} must be a boolean`;
    if ((t === "number" || t === "integer") && typeof value !== "number") return `input.${key} must be a number`;
    if (t === "object" && (typeof value !== "object" || value === null || Array.isArray(value))) return `input.${key} must be an object`;
    if (typeof value === "string") {
      if (typeof def["minLength"] === "number" && value.length < def["minLength"]) return `input.${key} is too short`;
      if (typeof def["maxLength"] === "number" && value.length > def["maxLength"]) return `input.${key} is too long`;
    }
    if (typeof value === "number" && typeof def["minimum"] === "number" && value < def["minimum"]) return `input.${key} is below the minimum`;
    if (Array.isArray(def["enum"]) && !def["enum"].includes(value)) return `input.${key} is not an allowed value`;
  }
  return undefined;
}

/** Route a mock API request. `path` may include a query string, e.g. /api/runs/x/timeline?after_seq=3. */
export function handleMockRequest(
  req: { method: string; path: string; body?: unknown },
  store: MockStore = sharedStore(),
  opts: Partial<EngineOptions> = {},
): MockResponse {
  const options: EngineOptions = { stepMs: opts.stepMs ?? DEFAULT_STEP_MS, now: opts.now ?? Date.now() };
  const url = new URL(req.path, "http://mock.local");
  const parts = url.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (parts[0] !== "api") return err(404, "not_found", "unknown path");
  const [, resource, id, sub, subId] = parts;
  const method = req.method.toUpperCase();

  if (resource === "health" && !id && method === "GET") return ok(200, { status: "ok", contract_version: CONTRACT_VERSION, model_adapter: "mock" });
  if (resource === "workflows" && !id && method === "GET") return ok(200, MOCK_WORKFLOWS);

  if (resource === "runs" && !id && method === "POST") {
    const body = req.body as { workflow_id?: unknown; input?: unknown; workflow_version?: unknown } | null | undefined;
    if (!body || typeof body.workflow_id !== "string" || body.input === undefined) return err(422, "validation_error", "workflow_id and input are required");
    const wf = MOCK_WORKFLOWS.find((w) => w.workflow_id === body.workflow_id);
    if (!wf) return err(404, "workflow_not_found", "unknown workflow_id");
    const problem = validateInput(wf.input_schema, body.input);
    if (problem) return err(422, "validation_error", problem);
    const runId = store.newId();
    const approvalId = `appr-${runId.slice(0, 8)}`;
    const input = body.input as Record<string, unknown>;
    const run: MockRun = {
      id: runId,
      workflowId: wf.workflow_id,
      workflowVersion: wf.version,
      input,
      createdAt: options.now,
      script: buildScript(wf.workflow_id, input, approvalId),
      approvalId,
    };
    store.runs.set(runId, run);
    return ok(201, snapshot(run, options));
  }

  if (resource === "runs" && id) {
    const run = store.runs.get(id);
    if (!run) return err(404, "run_not_found", "run not found");

    if (!sub && method === "GET") return ok(200, snapshot(run, options));

    if (sub === "timeline" && method === "GET") {
      const afterRaw = url.searchParams.get("after_seq");
      const limitRaw = url.searchParams.get("limit");
      const after = afterRaw === null ? 0 : Number(afterRaw);
      const limit = limitRaw === null ? 200 : Number(limitRaw);
      if (!Number.isInteger(after) || after < 0 || !Number.isInteger(limit) || limit < 1 || limit > 500) return err(422, "validation_error", "after_seq/limit out of range");
      const all = eventsFor(run, options);
      const events = all.filter((e) => e.seq > after).slice(0, limit);
      const nextSeq = events.at(-1)?.seq ?? after;
      const terminal = isTerminalState(snapshot(run, options).run.state) && nextSeq >= (all.at(-1)?.seq ?? 0);
      return ok(200, { run_id: run.id, events, next_seq: nextSeq, terminal } satisfies TimelinePage);
    }

    if (sub === "approvals" && subId && method === "POST") {
      const body = req.body as { decision?: unknown; reason?: unknown } | null | undefined;
      const decision = body?.decision;
      if (decision !== "approve" && decision !== "deny") return err(422, "validation_error", "decision must be approve or deny");
      if (body?.reason !== undefined && body.reason !== null && (typeof body.reason !== "string" || body.reason.length > 500)) return err(422, "validation_error", "reason must be a string of at most 500 characters");
      if (subId !== run.approvalId) return err(404, "approval_error", "approval not found");
      const snap = snapshot(run, options);
      const ap = snap.approvals[0];
      if (!ap) return err(409, "approval_error", "approval has not been requested yet");
      if (ap.status !== "pending") return err(409, "approval_error", `approval is ${ap.status}, not pending`);
      if (Date.parse(ap.expires_at) < options.now) return err(409, "approval_error", "approval expired");
      run.decision = { value: decision, at: options.now, reason: typeof body?.reason === "string" ? body.reason : null };
      return ok(200, snapshot(run, options));
    }

    if (sub === "cancel" && method === "POST") {
      const state = snapshot(run, options).run.state;
      if (run.decision || !canCancel(state)) return err(409, "illegal_transition", `cannot cancel a run in state ${state}; cancel is only allowed before ACTION`);
      const reason = (req.body as { reason?: unknown } | null | undefined)?.reason;
      run.cancel = { at: options.now, reason: typeof reason === "string" ? reason : null };
      return ok(200, snapshot(run, options));
    }
  }

  return err(404, "not_found", "unknown path");
}
