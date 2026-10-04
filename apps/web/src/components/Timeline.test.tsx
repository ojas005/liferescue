import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EVENT_TYPES, RunResponseSchema, type TimelineEvent as Ev } from "@/lib/api/schemas";
import { EvidencePanel } from "./EvidencePanel";
import { PlanView } from "./PlanView";
import { ResultCard } from "./ResultCard";
import { StatusBadge } from "./StatusBadge";
import { Timeline } from "./Timeline";

let n = 0;
const ev = (type: string, payload: Record<string, unknown> = {}, step = "intent"): Ev =>
  ({ event_id: `e${++n}`, run_id: "r", seq: n, ts: "2026-10-04T00:00:00Z", step, type, payload }) as Ev;

describe("Timeline", () => {
  it("renders every contract event type in order, each with its step and type", () => {
    const events = EVENT_TYPES.map((t) => ev(t, {}, "plan"));
    render(<Timeline events={events} />);
    const items = screen.getAllByTestId("timeline-event");
    expect(items.map((i) => i.getAttribute("data-event-type"))).toEqual([...EVENT_TYPES]);
    expect(items.every((i) => within(i).getByTestId("event-step").textContent === "plan")).toBe(true);
    expect(within(items[0]!).getByText("Intent")).toBeInTheDocument();
    expect(within(items[9]!).getByText("State")).toBeInTheDocument();
  });

  it("labels mocked tool results as simulated, and only those", () => {
    render(
      <Timeline
        events={[
          ev("action", { step_id: "s2", tool: "dispatch_tow", status: "ok", mocked: true, output: {} }, "action"),
          ev("action", { step_id: "s1", tool: "web_search", status: "ok", mocked: false, output: {} }, "action"),
        ]}
      />,
    );
    const [a, b] = screen.getAllByTestId("timeline-event");
    expect(within(a!).getByTestId("simulated-badge")).toHaveTextContent("simulated");
    expect(within(b!).queryByTestId("simulated-badge")).toBeNull();
  });

  it("renders an unknown event type generically instead of crashing", () => {
    render(<Timeline events={[ev("brand_new")]} />);
    expect(screen.getByText("brand_new")).toBeInTheDocument();
    expect(screen.getByText(/unrecognised event type/)).toBeInTheDocument();
  });

  it("shows waiting / live states", () => {
    const { rerender } = render(<Timeline events={[]} live />);
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for the first event");
    rerender(<Timeline events={[ev("intent")]} live />);
    expect(screen.getByText("Updating live...")).toBeInTheDocument();
  });

  it("renders hostile payload text as inert text: no elements, no links, URLs defanged", () => {
    const evil = `<img src=x onerror="alert(1)"><script>alert(2)</script> https://evil.example/pay ![x](https://evil.example/p.png)`;
    const { container } = render(<Timeline events={[ev("intent", { summary: evil, entities: { message_excerpt: evil, nested: { list: [evil], url: "javascript:alert(3)" } } })]} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.innerHTML).not.toContain("<img");
    expect(container.innerHTML).not.toContain("https://evil.example"); // only the defanged form appears
    expect(container.textContent).toContain("hxxps://evil[.]example/pay");
    expect(container.textContent).toContain("onerror=");
    expect(screen.getAllByTestId("defanged-link").length).toBeGreaterThan(0);
  });

  it("highlights redacted values", () => {
    render(<Timeline events={[ev("intent", { api_key: "[REDACTED]" })]} />);
    expect(screen.getByTitle("Redacted by the platform")).toHaveTextContent("[REDACTED]");
  });
});

describe("EvidencePanel", () => {
  it("shows collected/missing keys, research queries and defanged source URLs; no links", () => {
    const events = [
      ev("evidence", { collected: ["description", "location"], missing: ["vehicle"] }, "evidence"),
      ev("research", { queries: ["roadside near X"], skipped: [], source_urls: ["https://roadside.example/dir"] }, "research"),
    ];
    const { container } = render(<EvidencePanel events={events} input={{ description: "see http://bad.example/x" }} />);
    const summary = within(screen.getByTestId("evidence-summary"));
    expect(summary.getByText("description")).toBeInTheDocument();
    expect(summary.getByText("vehicle")).toBeInTheDocument();
    expect(screen.getByTestId("source-url")).toHaveTextContent("hxxps://roadside[.]example/dir");
    expect(screen.getByTestId("submitted-input")).toHaveTextContent("hxxp://bad[.]example/x");
    expect(screen.getByText("untrusted data")).toBeInTheDocument();
    expect(container.querySelector("a")).toBeNull();
  });
  it("has an empty state", () => {
    render(<EvidencePanel events={[]} />);
    expect(screen.getByText("No evidence gathered yet.")).toBeInTheDocument();
  });
});

const baseRun = {
  run_id: "r",
  workflow_id: "w",
  workflow_version: "0.1.0",
  contract_version: "0.1.0",
  input: {},
  created_at: "t",
  updated_at: "t",
};

describe("PlanView / ResultCard / StatusBadge", () => {
  it("PlanView joins plan steps with policy decisions and shows exact params", () => {
    const snap = RunResponseSchema.parse({
      run: {
        ...baseRun,
        plan: [
          { step_id: "s1", action_type: "lookup", tool_name: "web_search", params: { query: "q" }, rationale: "Find options" },
          { step_id: "s2", action_type: "request_tow", tool_name: "dispatch_tow", params: { location: "NH48" }, rationale: "Send a tow" },
        ],
        decisions: [
          { step_id: "s1", outcome: "allow", risk: "low", rule_id: "read-ok", reason: "ok", policy_version: "p", action_digest: "d" },
          { step_id: "s2", outcome: "needs_approval", risk: "high", rule_id: "tow", reason: "must approve", policy_version: "p", action_digest: "d" },
        ],
      },
    });
    render(<PlanView snapshot={snap} />);
    const steps = screen.getAllByTestId("plan-step");
    expect(steps).toHaveLength(2);
    expect(steps[1]).toHaveTextContent("dispatch_tow");
    expect(steps[1]).toHaveTextContent("policy: needs approval (high risk)");
    expect(steps[1]).toHaveTextContent("NH48");
  });
  it("PlanView empty state", () => {
    render(<PlanView snapshot={undefined} />);
    expect(screen.getByText("No plan yet.")).toBeInTheDocument();
  });

  it("ResultCard shows terminal reason, simulated tool results and verification", () => {
    const snap = RunResponseSchema.parse({
      run: {
        ...baseRun,
        state: "completed",
        results: [{ tool_name: "dispatch_tow", status: "ok", output: { reference: "MOCK-1" }, mocked: true }],
        verification: { passed: true, checks: [{ check_id: "c1", passed: true, detail: "fine" }] },
      },
    });
    render(<ResultCard snapshot={snap} />);
    expect(screen.getByTestId("tool-result")).toHaveTextContent("simulated");
    expect(screen.getByTestId("verification")).toHaveTextContent("Verification: passed");
    expect(screen.getAllByTestId("status-badge")[0]).toHaveTextContent("Completed");
  });
  it("ResultCard placeholder while running", () => {
    render(<ResultCard snapshot={RunResponseSchema.parse({ run: { ...baseRun, state: "research" } })} />);
    expect(screen.getByText(/will appear here/)).toBeInTheDocument();
  });
  it("StatusBadge maps run states to readable labels and tolerates unknown values", () => {
    const { rerender } = render(<StatusBadge status="approval" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Awaiting approval");
    rerender(<StatusBadge status="weird_state" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Weird state");
  });
});
