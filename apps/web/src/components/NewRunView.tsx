"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { getApiClient } from "@/lib/api";
import { useWorkflows } from "@/hooks/useWorkflows";
import { mergeWorkflows } from "@/lib/workflows/catalog";
import { SchemaForm } from "./SchemaForm";

/** Run-submission page for ANY workflow: the form is rendered from the workflow's intent schema. */
export function NewRunView({ workflowId }: { workflowId: string }) {
  const router = useRouter();
  const { workflows, loading, error } = useWorkflows();
  const [submitting, setSubmitting] = useState(false);
  const entry = mergeWorkflows(workflows).find((e) => e.workflowId === workflowId);
  const schema = entry?.workflow?.input_schema;

  async function submit(input: Record<string, unknown>) {
    setSubmitting(true);
    try {
      const run = await getApiClient().createRun({ workflow_id: workflowId, input });
      router.push(`/runs/${encodeURIComponent(run.run.run_id)}`);
    } finally {
      setSubmitting(false);
    }
  }

  if (!entry) {
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-bold text-slate-900">Unknown workflow</h1>
        <p className="text-sm text-slate-700">
          {loading ? "Loading workflows..." : <>No workflow with id <code>{workflowId}</code> was reported by the API.</>}
        </p>
        <Link href="/" className="text-sm underline">Back to home</Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <Link href="/" className="text-sm text-slate-600 underline">All experiences</Link>
        <h1 className="mt-2 text-2xl font-bold text-slate-900">{entry.meta.product}</h1>
        <p className="mt-1 text-sm text-slate-700">{entry.meta.description}</p>
      </div>
      {error ? (
        <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          Could not load workflows from the API: {error}
        </p>
      ) : null}
      {loading ? <p role="status" className="text-sm text-slate-600">Loading the input form...</p> : null}
      {!loading && !schema ? (
        <p role="status" className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          The API did not provide an input schema for this workflow, so the form cannot be shown.
        </p>
      ) : null}
      {schema ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <SchemaForm schema={schema} onSubmit={submit} submitting={submitting} />
        </div>
      ) : null}
    </div>
  );
}
