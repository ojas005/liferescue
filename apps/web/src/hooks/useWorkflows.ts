"use client";

import { useEffect, useState } from "react";
import { getApiClient, type WorkflowSummary } from "@/lib/api";

export type WorkflowsState = {
  /** undefined while loading or on error. */
  workflows: WorkflowSummary[] | undefined;
  loading: boolean;
  error: string | undefined;
};

export function useWorkflows(): WorkflowsState {
  const [state, setState] = useState<WorkflowsState>({ workflows: undefined, loading: true, error: undefined });
  useEffect(() => {
    const ctrl = new AbortController();
    getApiClient()
      .listWorkflows(ctrl.signal)
      .then((workflows) => setState({ workflows, loading: false, error: undefined }))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setState({ workflows: undefined, loading: false, error: err instanceof Error ? err.message : "Unknown error" });
      });
    return () => ctrl.abort();
  }, []);
  return state;
}
