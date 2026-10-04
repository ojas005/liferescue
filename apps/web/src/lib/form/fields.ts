/**
 * Convert an intent JSON Schema into a flat list of form fields and back into a typed `input` object.
 * Deliberately tolerant: anything that is not understood becomes a JSON text field, never a crash.
 */
export type FieldKind = "string" | "textarea" | "number" | "integer" | "boolean" | "enum" | "json";

export type FieldDef = {
  name: string;
  label: string;
  description?: string;
  kind: FieldKind;
  required: boolean;
  options?: { value: string; label: string }[];
  /** Original JSON-schema type of the enum values so we can coerce back (string | number | boolean). */
  enumType?: "string" | "number";
  defaultValue?: unknown;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  minimum?: number;
  maximum?: number;
  placeholder?: string;
  /** Original type label shown for json fallback fields. */
  originalType?: string;
};

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | undefined => (typeof v === "string" && v.length > 0 ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

function humanize(name: string): string {
  const s = name.replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : name;
}

function primaryType(schema: Obj): string | undefined {
  const t = schema["type"];
  if (typeof t === "string") return t;
  if (Array.isArray(t)) return t.find((x): x is string => typeof x === "string" && x !== "null");
  return undefined;
}

export function fieldFromSchema(name: string, raw: unknown, required: boolean): FieldDef {
  const schema = isObj(raw) ? raw : {};
  const base: FieldDef = {
    name,
    label: str(schema["title"]) ?? humanize(name),
    description: str(schema["description"]),
    kind: "json",
    required,
    defaultValue: schema["default"],
    placeholder: str(schema["examples"] && Array.isArray(schema["examples"]) ? schema["examples"][0] : undefined),
  };

  const enumValues = Array.isArray(schema["enum"])
    ? (schema["enum"] as unknown[]).filter((v): v is string | number => typeof v === "string" || typeof v === "number")
    : undefined;
  if (enumValues && enumValues.length > 0) {
    const names = Array.isArray(schema["enumNames"]) ? (schema["enumNames"] as unknown[]) : [];
    return {
      ...base,
      kind: "enum",
      enumType: enumValues.every((v) => typeof v === "number") ? "number" : "string",
      options: enumValues.map((v, i) => ({ value: String(v), label: typeof names[i] === "string" ? (names[i] as string) : String(v) })),
    };
  }

  const type = primaryType(schema);
  const format = str(schema["format"]);
  const widget = str(schema["x-widget"]) ?? str(schema["widget"]) ?? str(schema["x-ui"]);

  switch (type) {
    case "string": {
      const maxLength = num(schema["maxLength"]);
      const singleLine = format !== undefined && ["uri", "url", "email", "date", "date-time", "time", "uuid", "hostname"].includes(format);
      const multiline = widget === "textarea" || format === "textarea" || (!singleLine && maxLength !== undefined && maxLength > 200);
      return {
        ...base,
        kind: multiline ? "textarea" : "string",
        minLength: num(schema["minLength"]),
        maxLength,
        pattern: str(schema["pattern"]),
      };
    }
    case "number":
    case "integer":
      return { ...base, kind: type, minimum: num(schema["minimum"]), maximum: num(schema["maximum"]) };
    case "boolean":
      return { ...base, kind: "boolean" };
    default:
      return { ...base, kind: "json", originalType: type ?? (schema["oneOf"] || schema["anyOf"] ? "oneOf/anyOf" : "unspecified") };
  }
}

/** Fields for an intent schema of shape {type: "object", properties, required}. Non-object schemas yield one JSON field. */
export function fieldsFromSchema(schema: unknown): FieldDef[] {
  if (!isObj(schema)) return [];
  const props = schema["properties"];
  if (!isObj(props)) {
    return [];
  }
  const required = new Set(Array.isArray(schema["required"]) ? (schema["required"] as unknown[]).filter((r): r is string => typeof r === "string") : []);
  return Object.entries(props).map(([name, def]) => fieldFromSchema(name, def, required.has(name)));
}

export type FormValues = Record<string, string | boolean>;

export function initialValues(fields: FieldDef[]): FormValues {
  const out: FormValues = {};
  for (const f of fields) {
    const d = f.defaultValue;
    if (f.kind === "boolean") out[f.name] = typeof d === "boolean" ? d : false;
    else if (f.kind === "json") out[f.name] = d !== undefined ? JSON.stringify(d, null, 2) : "";
    else out[f.name] = d !== undefined && d !== null ? String(d) : "";
  }
  return out;
}

export type BuildResult = { ok: true; value: Record<string, unknown> } | { ok: false; errors: Record<string, string> };

export function buildInput(fields: FieldDef[], values: FormValues): BuildResult {
  const errors: Record<string, string> = {};
  const value: Record<string, unknown> = {};

  for (const f of fields) {
    const raw = values[f.name];

    if (f.kind === "boolean") {
      // A checkbox always has a value. Required booleans just mean "present".
      value[f.name] = raw === true;
      continue;
    }

    const text = typeof raw === "string" ? raw : "";
    const empty = text.trim() === "";
    if (empty) {
      if (f.required) errors[f.name] = `${f.label} is required`;
      continue;
    }

    switch (f.kind) {
      case "string":
      case "textarea": {
        if (f.minLength !== undefined && text.length < f.minLength) errors[f.name] = `${f.label} must be at least ${f.minLength} characters`;
        else if (f.maxLength !== undefined && text.length > f.maxLength) errors[f.name] = `${f.label} must be at most ${f.maxLength} characters`;
        else if (f.pattern && !matchesPattern(f.pattern, text)) errors[f.name] = `${f.label} does not match the required format`;
        else value[f.name] = text;
        break;
      }
      case "number":
      case "integer": {
        const n = Number(text);
        if (!Number.isFinite(n)) errors[f.name] = `${f.label} must be a number`;
        else if (f.kind === "integer" && !Number.isInteger(n)) errors[f.name] = `${f.label} must be a whole number`;
        else if (f.minimum !== undefined && n < f.minimum) errors[f.name] = `${f.label} must be at least ${f.minimum}`;
        else if (f.maximum !== undefined && n > f.maximum) errors[f.name] = `${f.label} must be at most ${f.maximum}`;
        else value[f.name] = n;
        break;
      }
      case "enum": {
        const opt = f.options?.find((o) => o.value === text);
        if (!opt) errors[f.name] = `${f.label} must be one of the listed options`;
        else value[f.name] = f.enumType === "number" ? Number(opt.value) : opt.value;
        break;
      }
      case "json": {
        try {
          value[f.name] = JSON.parse(text);
        } catch {
          errors[f.name] = `${f.label} must be valid JSON`;
        }
        break;
      }
    }
  }

  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, value };
}

function matchesPattern(pattern: string, text: string): boolean {
  try {
    return new RegExp(pattern, "u").test(text);
  } catch {
    // An invalid or unsupported pattern in the schema must not block the user; the backend validates anyway.
    return true;
  }
}
