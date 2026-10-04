import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createApiClient, type ApiClient, type Approval } from "@/lib/api";
import { handleMockRequest, newStore } from "@/lib/mock/engine";
import { ApprovalPrompt } from "./ApprovalPrompt";
import { RunView } from "./RunView";

const approval: Approval = {
  approval_id: "a1",
  run_id: "r",
  step_id: "s2",
  bound_digest: "0123456789abcdef0123",
  status: "pending",
  risk: "high",
  summary: "request_tow: dispatch_tow {}",
  policy_version: "p",
  requested_at: "2026-10-04T00:00:00Z",
  expires_at: "2026-10-04T00:15:00Z",
  decided_by: null,
  decided_at: null,
  reason: null,
};

describe("ApprovalPrompt", () => {
  it("shows the request and reports approve / deny with id and optional reason", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPrompt approval={approval} onDecide={onDecide} />);
    expect(screen.getByRole("alertdialog")).toHaveTextContent("request_tow");
    await userEvent.type(screen.getByLabelText(/Reason/), "ok by me");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onDecide).toHaveBeenLastCalledWith("a1", "approve", "ok by me");
    await userEvent.click(screen.getByRole("button", { name: "Deny" }));
    expect(onDecide).toHaveBeenLastCalledWith("a1", "deny", "ok by me");
  });

  it("omits an empty reason", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPrompt approval={approval} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Deny" }));
    expect(onDecide).toHaveBeenLastCalledWith("a1", "deny", undefined);
  });

  it("disables both buttons while a decision is in flight, and shows a 409 message", async () => {
    let reject: (e: Error) => void = () => {};
    const onDecide = vi.fn().mockReturnValue(new Promise<void>((_, r) => (reject = r)));
    render(<ApprovalPrompt approval={approval} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("button", { name: "Approving..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeDisabled();
    reject(new Error("approval is expired, not pending"));
    expect(await screen.findByRole("alert")).toHaveTextContent("approval is expired, not pending");
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });
});

/** An ApiClient wired to the in-memory mock engine with a controllable clock: the whole contract, no network. */
function engineClient() {
  let n = 0;
  const store = newStore(() => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`);
  let now = 1_000_000;
  const calls: { method: string; path: string; body?: unknown }[] = [];
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ method: init?.method ?? "GET", path, body });
    const res = handleMockRequest({ method: init?.method ?? "GET", path, body }, store, { now, stepMs: 1000 });
    return new Response(JSON.stringify(res.body), { status: res.status });
  }) as unknown as typeof fetch;
  const client: ApiClient = createApiClient({ config: { baseUrl: "", useMock: true }, fetchImpl });
  return { client, calls, advance: (ms: number) => (now += ms) };
}

const badge = () => screen.getAllByTestId("status-badge")[0];

describe("RunView against the contract engine", () => {
  it("polls with after_seq, pauses at the approval prompt, posts {decision, reason}, then completes", async () => {
    const { client, calls, advance } = engineClient();
    const created = await client.createRun({ workflow_id: "vehicle_breakdown", input: { description: "flat tyre", location: "NH48" } });
    const id = created.run.run_id;
    advance(30_000);

    render(<RunView runId={id} client={client} intervalMs={20} />);
    const prompt = await screen.findByTestId("approval-prompt");
    expect(prompt).toHaveTextContent("dispatch_tow");
    expect(screen.getByTestId("approval-step")).toHaveTextContent("NH48"); // exact args being approved
    expect(badge()).toHaveTextContent("Awaiting approval");
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeInTheDocument();
    expect(screen.queryByTestId("tool-result")).toBeNull();

    await userEvent.type(screen.getByLabelText(/Reason/), "go ahead");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    const post = calls.find((c) => c.method === "POST" && c.path.includes("/approvals/"));
    expect(post?.path).toBe(`/api/runs/${id}/approvals/appr-00000000`);
    expect(post?.body).toEqual({ decision: "approve", reason: "go ahead" });

    advance(60_000);
    await waitFor(() => expect(badge()).toHaveTextContent("Completed"));
    expect(screen.queryByTestId("approval-prompt")).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull(); // not cancellable after ACTION
    expect(screen.getAllByTestId("simulated-badge").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("tool-result").every((t) => t.textContent?.includes("simulated"))).toBe(true);
    const seqs = screen.getAllByTestId("timeline-event").map((e) => Number(e.getAttribute("data-seq")));
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
    expect(new Set(seqs).size).toBe(seqs.length); // incremental fetching never duplicates events

    const timelineCalls = calls.filter((c) => c.path.includes("/timeline"));
    expect(timelineCalls[0]?.path).toContain("after_seq=0");
    expect(timelineCalls.some((c) => !c.path.endsWith("after_seq=0"))).toBe(true);
  });

  it("deny ends the run as denied without an action event", async () => {
    const { client, advance } = engineClient();
    const run = await client.createRun({ workflow_id: "life_admin", input: { goal: "renew insurance", category: "renewal" } });
    advance(30_000);
    render(<RunView runId={run.run.run_id} client={client} intervalMs={20} />);
    await userEvent.click(await screen.findByRole("button", { name: "Deny" }));
    advance(60_000);
    await waitFor(() => expect(badge()).toHaveTextContent("Denied"));
    expect(screen.getAllByTestId("timeline-event").map((e) => e.getAttribute("data-event-type"))).not.toContain("action");
  });

  it("cancel works before ACTION and ends cancelled", async () => {
    const { client, advance } = engineClient();
    const run = await client.createRun({ workflow_id: "life_admin", input: { goal: "renew insurance", category: "renewal" } });
    advance(2_500);
    render(<RunView runId={run.run.run_id} client={client} intervalMs={20} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    advance(1_000);
    await waitFor(() => expect(badge()).toHaveTextContent("Cancelled"));
    await waitFor(() => expect(screen.queryByText("Updating live...")).toBeNull());
  });

  it("a 409 from approve is surfaced as the ErrorResponse message", async () => {
    const { client, advance } = engineClient();
    const run = await client.createRun({ workflow_id: "life_admin", input: { goal: "renew insurance", category: "renewal" } });
    advance(30_000);
    const snap = await client.getRun(run.run.run_id);
    // someone else decides first (e.g. another tab)
    await client.decideApproval(run.run.run_id, snap.approvals[0]!.approval_id, "approve");
    render(<RunView runId={run.run.run_id} client={client} intervalMs={20} />);
    await waitFor(() => expect(screen.queryByTestId("approval-prompt")).toBeNull());
  });

  it("shows a load error for an unknown run (404 ErrorResponse)", async () => {
    const { client } = engineClient();
    render(<RunView runId="nope" client={client} intervalMs={20} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load this run: run not found/);
  });

  it("renders a hostile scam message from end to end as inert, defanged text", async () => {
    const { client, advance } = engineClient();
    const evil = "<img src=x onerror=alert(1)> http://evil.example/pay";
    const run = await client.createRun({ workflow_id: "scam_investigation", input: { message_text: evil, suspicious_url: "http://evil.example/pay" } });
    advance(30_000);
    const { container } = render(<RunView runId={run.run.run_id} client={client} intervalMs={20} />);
    await screen.findByTestId("approval-prompt");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a[href*='evil']")).toBeNull();
    expect(container.innerHTML).not.toContain("http://evil.example");
    expect(container.textContent).toContain("hxxp://evil[.]example/pay");
    expect(container.textContent).toContain("onerror=alert(1)");
  });
});
