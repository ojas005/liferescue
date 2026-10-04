import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MOCK_WORKFLOWS } from "@/lib/mock/fixtures";
import { mergeWorkflows } from "@/lib/workflows/catalog";

// A plain function (not vi.fn) so the spy does not attach its own rejection handler to the returned promise.
let listImpl: () => Promise<unknown> = async () => [];
const listWorkflows = () => listImpl();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, getApiClient: () => ({ listWorkflows, config: { baseUrl: "", useMock: false } }) };
});

import { HomeView } from "./HomeView";

describe("HomeView / workflow picker", () => {
  beforeEach(() => {
    listImpl = async () => [];
  });

  it("shows all three experiences from the API", async () => {
    listImpl = async () => MOCK_WORKFLOWS;
    render(<HomeView />);
    await waitFor(() => expect(screen.queryByText(/Checking available workflows/)).toBeNull());
    const cards = screen.getAllByTestId("workflow-card");
    expect(cards.map((c) => c.getAttribute("data-workflow-id"))).toEqual(["vehicle_breakdown", "scam_investigation", "life_admin"]);
    for (const name of ["LifeRescue", "ScamShield", "LifeOS"]) expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start with ScamShield" })).toHaveAttribute("href", "/workflows/scam_investigation");
  });

  it("falls back to built-in copy when the API is down", async () => {
    listImpl = () => Promise.reject(new Error("Could not reach the API"));
    render(<HomeView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the API");
    expect(screen.getAllByTestId("workflow-card")).toHaveLength(3);
  });
});

describe("mergeWorkflows", () => {
  it("appends unknown API workflows with generic copy", () => {
    const merged = mergeWorkflows([{ workflow_id: "future_flow", version: "0.1.0", title: "Future", description: "d", input_schema: {} }]);
    expect(merged.map((m) => m.workflowId)).toEqual(["vehicle_breakdown", "scam_investigation", "life_admin", "future_flow"]);
    expect(merged[3]?.meta.product).toBe("Future");
  });
});
