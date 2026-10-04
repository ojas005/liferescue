import { describe, expect, it } from "vitest";
import { RunResponseSchema, TimelinePageSchema, WorkflowListSchema, ErrorResponseSchema } from "@/lib/api/schemas";
import { handleMockRequest, newStore } from "./engine";

const STEP = 1000;

function setup(workflow = "scam_investigation", input: Record<string, unknown> = { message_text: "pay now <script>x</script> http://evil.example/a" }) {
  let n = 0;
  const store = newStore(() => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`);
  const t0 = 1_000_000;
  const call = (offset: number, method: string, path: string, body?: unknown) => handleMockRequest({ method, path, body }, store, { now: t0 + offset, stepMs: STEP });
  const create = call(0, "POST", "/api/runs", { workflow_id: workflow, input });
  const snap = RunResponseSchema.parse(create.body);
  const id = snap.run.run_id;
  const timeline = (offset: number, after = 0) => TimelinePageSchema.parse(call(offset, "GET", `/api/runs/${id}/timeline?after_seq=${after}`).body);
  const run = (offset: number) => RunResponseSchema.parse(call(offset, "GET", `/api/runs/${id}`).body);
  return { id, call, create, snap, timeline, run };
}

describe("mock API engine (contract 0.1.0 shapes)", () => {
  it("every response parses with the contract schemas", () => {
    const { snap, timeline, run } = setup();
    expect(snap.run.contract_version).toBe("0.1.0");
    timeline(60_000);
    run(60_000);
    expect(WorkflowListSchema.parse(handleMockRequest({ method: "GET", path: "/api/workflows" }, newStore()).body).map((w) => w.workflow_id)).toEqual([
      "vehicle_breakdown",
      "scam_investigation",
      "life_admin",
    ]);
    expect(handleMockRequest({ method: "GET", path: "/api/health" }, newStore()).body).toMatchObject({ status: "ok", contract_version: "0.1.0", model_adapter: "mock" });
  });

  it("POST /api/runs returns a run still at INTENT (client must poll); run ids are not sequential", () => {
    const { snap, id } = setup();
    expect(snap.run.state).toBe("intent");
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("advances over time and pauses at APPROVAL with a pending approval", () => {
    const { run, timeline } = setup();
    expect(run(0).run.state).toBe("intent");
    expect(run(2_500).run.state).toBe("evidence");
    const paused = run(60_000);
    expect(paused.run.state).toBe("approval");
    expect(paused.approvals).toHaveLength(1);
    expect(paused.approvals[0]).toMatchObject({ status: "pending", step_id: "s2" });
    expect(paused.run.plan).toHaveLength(2);
    expect(paused.run.decisions.map((d) => d.outcome)).toEqual(["allow", "needs_approval"]);
    // nothing proceeds without a decision, however long we wait
    const later = timeline(100_000_000);
    expect(later.terminal).toBe(false);
    expect(later.events.at(-1)?.type).toBe("approval");
  });

  it("timeline honours after_seq/next_seq and returns only newer events", () => {
    const { timeline } = setup();
    const first = timeline(3_500);
    expect(first.events.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
    expect(first.next_seq).toBe(4);
    const second = timeline(8_500, first.next_seq);
    expect(second.events[0]?.seq).toBe(5);
    expect(second.events.every((e) => e.seq > 4)).toBe(true);
    const none = timeline(3_500, 4);
    expect(none.events).toEqual([]);
    expect(none.next_seq).toBe(4);
  });

  it("approve resumes, actions are mocked, run completes and timeline becomes terminal", () => {
    const { id, call, run, timeline } = setup();
    const ap = run(60_000).approvals[0]!;
    const decided = RunResponseSchema.parse(call(60_000, "POST", `/api/runs/${id}/approvals/${ap.approval_id}`, { decision: "approve", reason: "looks right" }).body);
    expect(decided.approvals[0]).toMatchObject({ status: "approved", decided_by: "demo-user", reason: "looks right" });
    const done = run(120_000);
    expect(done.run.state).toBe("completed");
    expect(done.approvals[0]?.status).toBe("consumed");
    expect(done.run.results.every((r) => r.mocked)).toBe(true);
    expect(done.run.verification?.passed).toBe(true);
    const page = timeline(120_000);
    expect(page.terminal).toBe(true);
    const types = page.events.map((e) => e.type);
    expect(types).toContain("action");
    expect(types).toContain("audit");
    expect(page.events.filter((e) => e.type === "action").every((e) => e.payload["mocked"] === true)).toBe(true);
  });

  it("deny ends DENIED without any action event", () => {
    const { id, call, run, timeline } = setup();
    const ap = run(60_000).approvals[0]!;
    call(60_000, "POST", `/api/runs/${id}/approvals/${ap.approval_id}`, { decision: "deny" });
    const done = run(120_000);
    expect(done.run.state).toBe("denied");
    expect(done.run.terminal_reason).toMatch(/denied/);
    expect(timeline(120_000).events.map((e) => e.type)).not.toContain("action");
  });

  it("cancel works before ACTION and is rejected after it (409 ErrorResponse)", () => {
    const a = setup();
    const cancelled = RunResponseSchema.parse(a.call(2_000, "POST", `/api/runs/${a.id}/cancel`, { reason: "changed my mind" }).body);
    expect(cancelled.run.state).toBe("cancelled");
    expect(a.timeline(100_000).terminal).toBe(true);
    expect(a.run(100_000).run.state).toBe("cancelled");

    const b = setup();
    const ap = b.run(60_000).approvals[0]!;
    b.call(60_000, "POST", `/api/runs/${b.id}/approvals/${ap.approval_id}`, { decision: "approve" });
    const res = b.call(100_000, "POST", `/api/runs/${b.id}/cancel`, {});
    expect(res.status).toBe(409);
    expect(ErrorResponseSchema.parse(res.body).error).toBe("illegal_transition");
  });

  it("errors are ErrorResponse: 404 unknown run/workflow, 409 repeated decision, 422 invalid input", () => {
    const { id, call, run } = setup();
    const ap = run(60_000).approvals[0]!;
    for (const r of [
      call(0, "GET", "/api/runs/nope"),
      call(0, "POST", "/api/runs", { workflow_id: "nope", input: {} }),
      call(0, "POST", "/api/runs", { workflow_id: "life_admin", input: {} }),
      call(0, "POST", "/api/runs", { workflow_id: "life_admin", input: { goal: "g", category: "bills", surprise: 1 } }),
      call(60_000, "POST", `/api/runs/${id}/approvals/${ap.approval_id}`, { decision: "maybe" }),
      call(60_000, "POST", `/api/runs/${id}/approvals/other`, { decision: "approve" }),
      call(500, "POST", `/api/runs/${id}/approvals/${ap.approval_id}`, { decision: "approve" }),
    ]) {
      expect([404, 409, 422]).toContain(r.status);
      expect(ErrorResponseSchema.safeParse(r.body).success).toBe(true);
    }
    expect(call(60_000, "POST", `/api/runs/${id}/approvals/${ap.approval_id}`, { decision: "approve" }).status).toBe(200);
    expect(call(60_001, "POST", `/api/runs/${id}/approvals/${ap.approval_id}`, { decision: "approve" }).status).toBe(409);
  });

  it("422 messages never echo the submitted values", () => {
    const secret = "SECRET-CANARY-123";
    const { call } = setup();
    const r = call(0, "POST", "/api/runs", { workflow_id: "life_admin", input: { goal: "g", category: secret } });
    expect(r.status).toBe(422);
    expect(JSON.stringify(r.body)).not.toContain(secret);
  });

  it("untrusted input stays data in the snapshot", () => {
    const { run } = setup();
    expect(JSON.stringify(run(60_000).run.intent)).toContain("<script>x</script>");
  });
});
