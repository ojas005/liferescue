import { describe, expect, it } from "vitest";
import { buildInput, fieldsFromSchema, initialValues } from "./fields";

const schema = {
  type: "object",
  required: ["name", "kind"],
  properties: {
    name: { type: "string", title: "Your name", minLength: 2 },
    bio: { type: "string", maxLength: 1000 },
    age: { type: "integer", minimum: 0, maximum: 120 },
    amount: { type: "number" },
    agree: { type: "boolean", default: true },
    kind: { type: "string", enum: ["a", "b"] },
    level: { enum: [1, 2, 3] },
    weird: { type: "array", items: {} },
    nullable: { type: ["string", "null"] },
  },
};

describe("fieldsFromSchema", () => {
  it("maps JSON-schema types to field kinds with a graceful fallback", () => {
    const f = Object.fromEntries(fieldsFromSchema(schema).map((x) => [x.name, x]));
    expect(f["name"]).toMatchObject({ kind: "string", label: "Your name", required: true });
    expect(f["bio"]?.kind).toBe("textarea");
    expect(fieldsFromSchema({ properties: { u: { type: "string", format: "uri", maxLength: 2048 } } })[0]?.kind).toBe("string");
    expect(f["age"]).toMatchObject({ kind: "integer", minimum: 0, maximum: 120 });
    expect(f["amount"]?.kind).toBe("number");
    expect(f["agree"]?.kind).toBe("boolean");
    expect(f["kind"]?.kind).toBe("enum");
    expect(f["level"]).toMatchObject({ kind: "enum", enumType: "number" });
    expect(f["weird"]).toMatchObject({ kind: "json", originalType: "array" });
    expect(f["nullable"]?.kind).toBe("string");
  });
  it("returns no fields for junk schemas", () => {
    expect(fieldsFromSchema(undefined)).toEqual([]);
    expect(fieldsFromSchema("x")).toEqual([]);
    expect(fieldsFromSchema({ type: "object" })).toEqual([]);
  });
});

describe("buildInput", () => {
  const fields = fieldsFromSchema(schema);
  it("reports required and constraint errors", () => {
    const r = buildInput(fields, { ...initialValues(fields), name: "a", age: "200" });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.errors["name"]).toMatch(/at least 2/);
      expect(r.errors["age"]).toMatch(/at most 120/);
      expect(r.errors["kind"]).toMatch(/required/);
    }
  });
  it("coerces types and omits empty optional fields", () => {
    const r = buildInput(fields, { ...initialValues(fields), name: "Ada", kind: "b", age: "42", amount: "1.5", level: "2", weird: "[1,2]", agree: false });
    expect(r).toEqual({ ok: true, value: { name: "Ada", kind: "b", age: 42, amount: 1.5, level: 2, weird: [1, 2], agree: false } });
  });
  it("rejects invalid JSON and non-integers", () => {
    const r = buildInput(fields, { ...initialValues(fields), name: "Ada", kind: "a", weird: "{oops", age: "1.5" });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.errors["weird"]).toMatch(/valid JSON/);
      expect(r.errors["age"]).toMatch(/whole number/);
    }
  });
});
