import { z } from "zod";
import { resolveConfig, type ApiConfig } from "./config";
import {
  ErrorResponseSchema,
  HealthResponseSchema,
  RunResponseSchema,
  TimelinePageSchema,
  WorkflowListSchema,
  type ApprovalDecision,
  type CreateRunRequest,
  type HealthResponse,
  type RunResponse,
  type TimelinePage,
  type WorkflowSummary,
} from "./schemas";

/**
 * Failure talking to the API.
 *  - "network": could not reach it
 *  - "http":    non-2xx. For 404/409/422 the body is the contract's ErrorResponse -> `code` + message
 *  - "parse":   2xx but not valid JSON / not matching the contract
 */
export class ApiError extends Error {
  readonly kind: "network" | "http" | "parse";
  readonly status: number | undefined;
  /** ErrorResponse.error, when the body was an ErrorResponse. */
  readonly code: string | undefined;
  constructor(kind: "network" | "http" | "parse", message: string, status?: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.code = code;
  }
}

export type FetchLike = typeof fetch;

export type ApiClient = {
  config: ApiConfig;
  listWorkflows(signal?: AbortSignal): Promise<WorkflowSummary[]>;
  createRun(req: CreateRunRequest, signal?: AbortSignal): Promise<RunResponse>;
  getRun(runId: string, signal?: AbortSignal): Promise<RunResponse>;
  getTimeline(runId: string, afterSeq?: number, signal?: AbortSignal): Promise<TimelinePage>;
  decideApproval(runId: string, approvalId: string, decision: ApprovalDecision, reason?: string, signal?: AbortSignal): Promise<RunResponse>;
  cancelRun(runId: string, reason?: string, signal?: AbortSignal): Promise<RunResponse>;
  health(signal?: AbortSignal): Promise<HealthResponse>;
};

async function errorFrom(res: Response): Promise<ApiError> {
  let text = "";
  try {
    text = await res.text();
  } catch {
    /* ignore */
  }
  try {
    const parsed = ErrorResponseSchema.safeParse(JSON.parse(text));
    if (parsed.success) return new ApiError("http", parsed.data.message, res.status, parsed.data.error);
  } catch {
    /* not JSON */
  }
  // Not an ErrorResponse (e.g. a proxy page or a framework default). Keep it short; it is shown as plain text.
  return new ApiError("http", `API returned ${res.status}${text ? `: ${text.slice(0, 200)}` : ""}`, res.status);
}

export function createApiClient(options: { config?: ApiConfig; fetchImpl?: FetchLike } = {}): ApiClient {
  const config = options.config ?? resolveConfig();
  const doFetch: FetchLike = options.fetchImpl ?? ((...args) => fetch(...args));

  async function request<S extends z.ZodType>(
    method: "GET" | "POST",
    path: string,
    schema: S,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<z.output<S>> {
    let res: Response;
    try {
      res = await doFetch(`${config.baseUrl}${path}`, {
        method,
        headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal,
        // No ambient credentials: the sprint contract has no auth (single demo-user).
        credentials: "omit",
        cache: "no-store",
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new ApiError("network", "Could not reach the API");
    }
    if (!res.ok) throw await errorFrom(res);
    let json: unknown;
    try {
      json = JSON.parse(await res.text());
    } catch {
      throw new ApiError("parse", "API returned a response that is not valid JSON", res.status);
    }
    const parsed = schema.safeParse(json);
    if (!parsed.success) {
      const first = parsed.error.issues[0];
      const where = first && first.path.length > 0 ? ` at ${first.path.join(".")}` : "";
      throw new ApiError("parse", `API response did not match contract 0.1.0${where}`, res.status);
    }
    return parsed.data;
  }

  const enc = encodeURIComponent;
  return {
    config,
    listWorkflows: (signal) => request("GET", "/api/workflows", WorkflowListSchema, undefined, signal),
    createRun: (req, signal) => request("POST", "/api/runs", RunResponseSchema, req, signal),
    getRun: (id, signal) => request("GET", `/api/runs/${enc(id)}`, RunResponseSchema, undefined, signal),
    getTimeline: (id, afterSeq = 0, signal) =>
      request("GET", `/api/runs/${enc(id)}/timeline?after_seq=${Math.max(0, Math.trunc(afterSeq))}`, TimelinePageSchema, undefined, signal),
    decideApproval: (runId, approvalId, decision, reason, signal) =>
      request(
        "POST",
        `/api/runs/${enc(runId)}/approvals/${enc(approvalId)}`,
        RunResponseSchema,
        { decision, ...(reason ? { reason } : {}) },
        signal,
      ),
    cancelRun: (id, reason, signal) =>
      request("POST", `/api/runs/${enc(id)}/cancel`, RunResponseSchema, reason ? { reason } : {}, signal),
    health: (signal) => request("GET", "/api/health", HealthResponseSchema, undefined, signal),
  };
}

let shared: ApiClient | undefined;
/** App-wide client built from NEXT_PUBLIC_* config. */
export function getApiClient(): ApiClient {
  shared ??= createApiClient();
  return shared;
}
