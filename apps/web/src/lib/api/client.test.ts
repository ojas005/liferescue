import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";
import { resolveConfig } from "./config";
import { canCancel, isSimulated, pendingApprovals, RunResponseSchema, TimelinePageSchema, WorkflowListSchema } from "./schemas";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
const cfg = { baseUrl: "http://api.test", useMock: false };

const runResponse = {
  run: {
    run_id: "r1",
    workflow_id: "vehicle_breakdown",
    workflow_version: "0.1.0",
    contract_version: "0.1.0",
    input: { description: "x" },
    created_at: "2026-10-04T00:00:00Z",
    updated_at: "2026-10-04T00:00:00Z",
  },
};

describe("resolveConfig", () => {
  it("strips trailing slashes and defaults to real mode", () => {
    expect(resolveConfig({ NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000//" })).toEqual({ baseUrl: "http://localhost:8000", useMock: false });
  });
  it("mock mode is a switch and ignores the base URL", () => {
    expect(resolveConfig({ NEXT_PUBLIC_USE_MOCK: "1", NEXT_PUBLIC_API_BASE_URL: "http://x" })).toEqual({ baseUrl: "", useMock: true });
  });
});

describe("schemas", () => {
  it("applies contract defaults (state intent, owner demo-user, empty lists)", () => {
    const r = RunResponseSchema.parse(runResponse);
    expect(r.run).toMatchObject({ state: "intent", owner: "demo-user", plan: [], results: [], intent: null, verification: null });
    expect(r.approvals).toEqual([]);
    expect(r.last_seq).toBe(0);
  });
  it("keeps unknown additive keys but rejects unknown enum values (breaking change)", () => {
    expect(RunResponseSchema.parse({ ...runResponse, extra_new_field: 1 })).toHaveProperty("extra_new_field", 1);
    expect(RunResponseSchema.safeParse({ run: { ...runResponse.run, state: "teleporting" } }).success).toBe(false);
  });
  it("rejects a workflow list that is not a bare array", () => {
    expect(WorkflowListSchema.safeParse({ workflows: [] }).success).toBe(false);
  });
  it("timeline page requires next_seq and terminal", () => {
    expect(TimelinePageSchema.safeParse({ run_id: "r", events: [] }).success).toBe(false);
    expect(TimelinePageSchema.safeParse({ run_id: "r", events: [], next_seq: 0, terminal: false }).success).toBe(true);
  });
  it("helpers: pendingApprovals, canCancel, isSimulated", () => {
    const ap = { approval_id: "a", run_id: "r", step_id: "s", bound_digest: "d", risk: "low", summary: "s", policy_version: "p", requested_at: "t", expires_at: "t" };
    const r = RunResponseSchema.parse({ ...runResponse, approvals: [{ ...ap, status: "pending" }, { ...ap, approval_id: "b", status: "approved" }] });
    expect(pendingApprovals(r).map((a) => a.approval_id)).toEqual(["a"]);
    expect(canCancel("approval")).toBe(true);
    expect(canCancel("action")).toBe(false);
    expect(canCancel("completed")).toBe(false);
    expect(isSimulated({ mocked: true })).toBe(true);
    expect(isSimulated({ result: { mocked: true } })).toBe(true);
    expect(isSimulated({ mocked: false })).toBe(false);
    expect(isSimulated(null)).toBe(false);
  });
});

describe("api client", () => {
  it("GET /api/workflows parses a bare array, no credentials", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([{ workflow_id: "vehicle_breakdown", version: "0.1.0", title: "t", description: "d", input_schema: { type: "object" } }]));
    const wfs = await createApiClient({ config: cfg, fetchImpl }).listWorkflows();
    expect(wfs[0]?.workflow_id).toBe("vehicle_breakdown");
    expect(fetchImpl).toHaveBeenCalledWith("http://api.test/api/workflows", expect.objectContaining({ method: "GET", credentials: "omit" }));
  });

  it("POST /api/runs sends {workflow_id, input} and returns a RunResponse", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(runResponse, 201));
    const r = await createApiClient({ config: cfg, fetchImpl }).createRun({ workflow_id: "vehicle_breakdown", input: { description: "x" } });
    expect(r.run.run_id).toBe("r1");
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.test/api/runs");
    expect(JSON.parse(init.body as string)).toEqual({ workflow_id: "vehicle_breakdown", input: { description: "x" } });
  });

  it("GET timeline passes after_seq", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ run_id: "r1", events: [], next_seq: 7, terminal: false }));
    const page = await createApiClient({ config: cfg, fetchImpl }).getTimeline("r1", 7);
    expect(page.next_seq).toBe(7);
    expect(fetchImpl.mock.calls[0]?.[0]).toBe("http://api.test/api/runs/r1/timeline?after_seq=7");
  });

  it("POST approval sends {decision, reason}, encodes ids and returns the run", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(runResponse));
    await createApiClient({ config: cfg, fetchImpl }).decideApproval("run/1", "appr 1", "deny", "too risky");
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.test/api/runs/run%2F1/approvals/appr%201");
    expect(JSON.parse(init.body as string)).toEqual({ decision: "deny", reason: "too risky" });
  });

  it("POST cancel", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(runResponse));
    await createApiClient({ config: cfg, fetchImpl }).cancelRun("r1");
    expect(fetchImpl.mock.calls[0]?.[0]).toBe("http://api.test/api/runs/r1/cancel");
    expect((fetchImpl.mock.calls[0] as [string, RequestInit])[1].method).toBe("POST");
  });

  it("maps 404/409/422 ErrorResponse bodies to ApiError with code and message", async () => {
    for (const status of [404, 409, 422]) {
      const api = createApiClient({ config: cfg, fetchImpl: vi.fn().mockResolvedValue(jsonResponse({ error: "approval_error", message: "approval is denied, not pending" }, status)) });
      await expect(api.getRun("x")).rejects.toMatchObject({ kind: "http", status, code: "approval_error", message: "approval is denied, not pending" });
    }
  });

  it("copes with non-ErrorResponse error bodies, bad JSON, contract mismatch and network failure", async () => {
    const mk = (f: () => Promise<Response>) => createApiClient({ config: cfg, fetchImpl: vi.fn().mockImplementation(f) });
    await expect(mk(async () => jsonResponse({ detail: "boom" }, 500)).getRun("x")).rejects.toMatchObject({ kind: "http", status: 500, code: undefined });
    await expect(mk(async () => new Response("<html>", { status: 200 })).getRun("x")).rejects.toMatchObject({ kind: "parse" });
    await expect(mk(async () => jsonResponse({ nope: true })).getRun("x")).rejects.toMatchObject({ kind: "parse" });
    await expect(mk(async () => { throw new TypeError("fail"); }).getRun("x")).rejects.toBeInstanceOf(ApiError);
  });
});
