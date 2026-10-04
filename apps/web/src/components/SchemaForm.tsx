"use client";

import { useId, useMemo, useState, type FormEvent } from "react";
import { buildInput, fieldsFromSchema, initialValues, type FieldDef, type FormValues } from "@/lib/form/fields";

type Props = {
  /** Intent JSON Schema ({type: "object", properties, required}). */
  schema: unknown;
  onSubmit: (input: Record<string, unknown>) => Promise<void> | void;
  submitting?: boolean;
  submitLabel?: string;
};

const inputCls =
  "mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900 aria-[invalid=true]:border-rose-500";

export function SchemaForm({ schema, onSubmit, submitting = false, submitLabel = "Start run" }: Props) {
  const uid = useId();
  const fields = useMemo(() => fieldsFromSchema(schema), [schema]);
  const [values, setValues] = useState<FormValues>(() => initialValues(fields));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string>();

  if (fields.length === 0) {
    return (
      <p role="status" className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
        This workflow does not declare any input fields.
        <button
          type="button"
          disabled={submitting}
          onClick={() => void onSubmit({})}
          className="ml-3 rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {submitLabel}
        </button>
      </p>
    );
  }

  function set(name: string, v: string | boolean) {
    setValues((prev) => ({ ...prev, [name]: v }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitError(undefined);
    const result = buildInput(fields, values);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors({});
    try {
      await onSubmit(result.value);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Submit failed");
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5" aria-label="Run input">
      {fields.map((f) => (
        <Field key={f.name} uid={uid} field={f} value={values[f.name]} error={errors[f.name]} onChange={(v) => set(f.name, v)} />
      ))}
      {submitError ? (
        <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          {submitError}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "Starting..." : submitLabel}
      </button>
    </form>
  );
}

function Field({
  uid,
  field: f,
  value,
  error,
  onChange,
}: {
  uid: string;
  field: FieldDef;
  value: string | boolean | undefined;
  error?: string;
  onChange: (v: string | boolean) => void;
}) {
  const id = `${uid}-${f.name}`;
  const descId = f.description ? `${id}-desc` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [descId, errId].filter(Boolean).join(" ") || undefined;
  const common = { id, name: f.name, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined, "aria-required": f.required || undefined } as const;
  const text = typeof value === "string" ? value : "";

  const label = (
    <>
      {f.label}
      {f.required ? (
        <span className="ml-1 text-rose-700" aria-hidden>
          *
        </span>
      ) : (
        <span className="ml-1 text-xs font-normal text-slate-500">(optional)</span>
      )}
    </>
  );

  let control: React.ReactNode;
  switch (f.kind) {
    case "boolean":
      return (
        <div>
          <label htmlFor={id} className="flex items-start gap-2 text-sm font-medium text-slate-900">
            <input
              {...common}
              type="checkbox"
              checked={value === true}
              onChange={(e) => onChange(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-slate-300"
            />
            <span>
              {f.label}
              {f.required ? <span className="sr-only"> (required)</span> : null}
            </span>
          </label>
          {f.description ? (
            <p id={descId} className="ml-6 mt-0.5 text-xs text-slate-600">
              {f.description}
            </p>
          ) : null}
        </div>
      );
    case "textarea":
      control = <textarea {...common} rows={5} value={text} onChange={(e) => onChange(e.target.value)} placeholder={f.placeholder} className={inputCls} />;
      break;
    case "enum":
      control = (
        <select {...common} value={text} onChange={(e) => onChange(e.target.value)} className={inputCls}>
          <option value="">{f.required ? "Select..." : "(none)"}</option>
          {f.options?.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
      break;
    case "number":
    case "integer":
      control = (
        <input
          {...common}
          type="number"
          inputMode={f.kind === "integer" ? "numeric" : "decimal"}
          step={f.kind === "integer" ? 1 : "any"}
          min={f.minimum}
          max={f.maximum}
          value={text}
          onChange={(e) => onChange(e.target.value)}
          placeholder={f.placeholder}
          className={inputCls}
        />
      );
      break;
    case "json":
      control = (
        <>
          <textarea {...common} rows={4} value={text} onChange={(e) => onChange(e.target.value)} spellCheck={false} placeholder='{"key": "value"}' className={`${inputCls} font-mono`} />
          <p className="mt-1 text-xs text-slate-500">
            Type &quot;{f.originalType ?? "unspecified"}&quot; has no dedicated control; enter JSON.
          </p>
        </>
      );
      break;
    default:
      control = <input {...common} type="text" value={text} onChange={(e) => onChange(e.target.value)} placeholder={f.placeholder} className={inputCls} />;
  }

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-900">
        {label}
      </label>
      {f.description ? (
        <p id={descId} className="mt-0.5 text-xs text-slate-600">
          {f.description}
        </p>
      ) : null}
      {control}
      {error ? (
        <p id={errId} role="alert" className="mt-1 text-xs font-medium text-rose-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
