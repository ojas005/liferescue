import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MOCK_WORKFLOWS } from "@/lib/mock/fixtures";
import { SchemaForm } from "./SchemaForm";

const schema = {
  type: "object",
  required: ["title", "kind"],
  properties: {
    title: { type: "string", title: "Title", description: "Short title" },
    notes: { type: "string", title: "Notes", maxLength: 5000 },
    count: { type: "integer", title: "Count", minimum: 1 },
    urgent: { type: "boolean", title: "Urgent" },
    kind: { type: "string", title: "Kind", enum: ["x", "y"] },
    blob: { type: "object", title: "Blob" },
  },
};

describe("SchemaForm", () => {
  it("renders each field type with labels, descriptions and required markers", () => {
    render(<SchemaForm schema={schema} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText(/Title/)).toHaveAttribute("type", "text");
    expect(screen.getByLabelText(/Title/)).toHaveAttribute("aria-required", "true");
    expect(screen.getByText("Short title")).toBeInTheDocument();
    expect(screen.getByLabelText(/Notes/).tagName).toBe("TEXTAREA");
    expect(screen.getByLabelText(/Count/)).toHaveAttribute("type", "number");
    expect(screen.getByLabelText(/Urgent/)).toHaveAttribute("type", "checkbox");
    expect(screen.getByLabelText(/Kind/).tagName).toBe("SELECT");
    expect(screen.getByRole("option", { name: "y" })).toBeInTheDocument();
    // unknown type falls back to a JSON textarea
    expect(screen.getByLabelText(/Blob/).tagName).toBe("TEXTAREA");
    expect(screen.getByText(/has no dedicated control/)).toBeInTheDocument();
  });

  it("blocks submit and shows errors when required fields are missing", async () => {
    const onSubmit = vi.fn();
    render(<SchemaForm schema={schema} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText("Title is required")).toBeInTheDocument();
    expect(screen.getByText("Kind is required")).toBeInTheDocument();
  });

  it("submits a correctly typed input object", async () => {
    const onSubmit = vi.fn();
    render(<SchemaForm schema={schema} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText(/Title/), "Hello");
    await userEvent.type(screen.getByLabelText(/Count/), "3");
    await userEvent.click(screen.getByLabelText(/Urgent/));
    await userEvent.selectOptions(screen.getByLabelText(/Kind/), "y");
    await userEvent.type(screen.getByLabelText(/Blob/), '{{"a":1}');
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith({ title: "Hello", count: 3, urgent: true, kind: "y", blob: { a: 1 } });
  });

  it("shows the error from a failing submit and disables while submitting", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("API returned 422"));
    const { rerender } = render(<SchemaForm schema={{ type: "object", properties: { a: { type: "string" } } }} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("API returned 422");
    rerender(<SchemaForm schema={{ type: "object", properties: { a: { type: "string" } } }} onSubmit={onSubmit} submitting />);
    expect(screen.getByRole("button", { name: "Starting..." })).toBeDisabled();
  });

  it("renders every mock workflow schema without crashing", () => {
    for (const wf of MOCK_WORKFLOWS) {
      const { unmount } = render(<SchemaForm schema={wf.input_schema} onSubmit={vi.fn()} />);
      expect(screen.getByRole("form", { name: "Run input" })).toBeInTheDocument();
      unmount();
    }
  });

  it("renders the contract's vehicle_breakdown schema generically (no hard-coded fields)", async () => {
    const onSubmit = vi.fn();
    const vb = MOCK_WORKFLOWS.find((w) => w.workflow_id === "vehicle_breakdown")!;
    render(<SchemaForm schema={vb.input_schema} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText("Description is required")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Description/), "flat");
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith({ description: "flat" });
  });

  it("copes with a schema without properties", () => {
    render(<SchemaForm schema={{ type: "object" }} onSubmit={vi.fn()} />);
    expect(screen.getByText(/does not declare any input fields/)).toBeInTheDocument();
  });
});
