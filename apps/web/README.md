# apps/web - LifeRescue common web shell

One Next.js (App Router, TypeScript, Tailwind) UI for **all three experiences**: LifeRescue (`vehicle_breakdown`),
ScamShield (`scam_investigation`) and LifeOS (`life_admin`). There are no per-workflow screens: every workflow uses
the same `SchemaForm`, `Timeline`, `EvidencePanel`, `PlanView`, `ApprovalPrompt` and `ResultCard`.

Owner: LR 05 (Frontend). Consumes **platform contract 0.1.0** (`contract/openapi.yaml`, a verbatim copy of
`packages/contract/openapi.yaml`, owned by LR 03). It never imports Python.

## Run it

```bash
npm install            # from the repository root (npm workspaces)
cd apps/web
npm run dev:mock       # http://localhost:3005 against the built-in MOCK API (banner shown)
npm run dev            # http://localhost:3005 against a real API, see "Configuration"
```

Scripts (run in `apps/web`, or from the repo root where `lint|typecheck|test|build|dev` are forwarded):

| script | what it does |
|---|---|
| `npm run lint` | ESLint (flat config; `react/no-danger` is an error) |
| `npm run typecheck` | `tsc --noEmit` (also checks zod schemas are assignable to the generated contract types) |
| `npm test` | vitest + Testing Library |
| `npm run build` | `next build` |
| `npm run gen:api` | regenerate `src/lib/api/generated/openapi.d.ts` from `contract/openapi.yaml` (openapi-typescript) |
| `npm run check:api` | fails if the generated types are stale w.r.t. `contract/openapi.yaml` |
| `npm run dev:mock` / `build:mock` | same as dev/build with `NEXT_PUBLIC_USE_MOCK=1` |

## Configuration (non-secret only)

| variable | meaning |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | base URL of the FastAPI backend, e.g. `http://localhost:8000` (no trailing slash). Empty = same origin. |
| `NEXT_PUBLIC_USE_MOCK` | `1` = use the built-in MOCK API (Next route handlers at `/api/*`) and show the **MOCK API** banner. |

`NEXT_PUBLIC_*` values are shipped to every browser: **never put keys or tokens there** (a test enforces this). The
browser only talks to the run API; only `apps/api` ever holds model/Tavily keys. The backend must allow the web origin
in CORS (SECURITY A1); the CSP `connect-src` is limited to `'self'` plus the origin of `NEXT_PUBLIC_API_BASE_URL`.

## Contract usage (0.1.0)

- Types are generated (`src/lib/api/generated/openapi.d.ts`); `src/lib/api/schemas.ts` holds the zod runtime guards and a
  compile-time conformance check against the generated types. Swap contract versions by replacing
  `contract/openapi.yaml`, running `npm run gen:api`, and fixing whatever `npm run typecheck` reports.
- Start: `GET /api/workflows` (bare array of `WorkflowSummary`) -> pick -> intake form rendered from `input_schema`
  -> `POST /api/runs {workflow_id, input}` -> `/runs/{run_id}`. The create response may still be at `intent`; the UI always polls.
- Run page polls `GET /api/runs/{id}` and `GET /api/runs/{id}/timeline?after_seq=<next_seq>` until `terminal` is true.
  Each event shows its `step` and `type`; payloads are redacted by the platform and rendered as inert text.
- Approval cards come from `RunResponse.approvals` with `status: "pending"` and submit
  `POST /api/runs/{id}/approvals/{approval_id} {decision: "approve"|"deny", reason?}`. The card shows the exact tool and
  params from the plan step it is bound to.
- Cancel (`POST /api/runs/{id}/cancel`) is offered only in states before `action`.
- Errors: 404/409/422 bodies are `ErrorResponse {error, message}`; the message is shown as text.
- Tool results with `mocked: true` are labelled **simulated**.

## Untrusted content (SECURITY U6)

Scam messages, URLs, user input, evidence and model text are data. They are rendered by React as text only: no
`dangerouslySetInnerHTML`, no markdown/HTML rendering, no images or remote content. URLs found in text are **defanged**
(`hxxps://example[.]com`), never become links, are never fetched, and have a Copy button.

## Security headers

`next.config.ts` sets CSP (`default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`, no remote images),
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`.
Known limitation: `script-src` has `'unsafe-inline'` (Next inline bootstrap) until a nonce CSP is added.

## Mock API (dev/test fixture only)

`src/app/api/[[...path]]/route.ts` + `src/lib/mock/*` serve the contract shapes in memory when `NEXT_PUBLIC_USE_MOCK=1`
(otherwise they return 404). A run advances through intent -> evidence -> research -> plan -> policy -> approval, **pauses until
approved/denied**, then action (all tool results `mocked: true`) -> verification -> audit -> completed. The `vehicle_breakdown`
input schema is the contract fixture's; the other two workflows' schemas are invented to exercise the generic form. The mock
contains no AI output and the UI shows a **MOCK API** banner whenever it is active. Mock state lives in server memory.

## Layout

```
contract/openapi.yaml        frozen contract copy (source of truth for types)
src/app/                     routes: /, /workflows/[id] (intake), /runs/[id], mock /api/*
src/components/              shared components (Timeline, TimelineEvent, EvidencePanel, PlanView, ApprovalPrompt,
                             ResultCard, SchemaForm, WorkflowCard, StatusBadge, ...)
src/lib/api/                 zod schemas, typed client, config, generated types
src/lib/form/fields.ts       JSON-schema -> form fields -> typed input
src/lib/mock/                mock engine + fixtures
src/lib/security/headers.ts  CSP and friends
src/lib/workflows/catalog.ts marketing copy keyed by workflow_id (fallback when the API omits it)
```
