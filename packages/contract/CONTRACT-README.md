# CONTRACT-README — LifeRescue platform contract `0.1.0`

Package `contract` (target path `packages/contract/`). Python 3.11+, pydantic v2. Everything here is **Proposed for the sprint**; items marked
**PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** are choices the brief left open. Owner: LR 03.

## 1. What is in it (import these)
| File | Purpose |
|---|---|
| `contract/__init__.py` | `CONTRACT_VERSION = "0.1.0"` |
| `contract/models.py` | all data models, enums, `ActionRequest.digest()`, `RunRecord`, `TimelineEvent`, `Approval`, ... |
| `contract/workflow_definition.py` | `WorkflowDefinition` (+ sub-specs and validators) |
| `contract/run_state_machine.py` | `ALLOWED_TRANSITIONS`, `TransitionContext`, `apply_transition` |
| `contract/interfaces.py` | Protocols: `ModelGateway ToolGateway ResearchProvider PolicyEngine ApprovalService Verifier AuditLog RunStore WorkflowRegistry RunEngine` |
| `contract/api_models.py` + `openapi.yaml` | HTTP request/response models; generated spec (`python -m contract.openapi_gen openapi.yaml`) |
| `contract/validation.py`, `actions.py`, `redaction.py`, `errors.py` | input validation, shared action-digest builder, payload redaction, error types |
| `contract/arch_check.py` | static ONE-runtime import checks (R1-R6) |
| `contract/fakes/*`, `contract/fixtures/*` | **tests/dev only**: in-memory implementations, `build_fake_stack()`, `vehicle_breakdown()` example |

Pipeline: `INTENT -> EVIDENCE -> RESEARCH -> PLAN -> POLICY -> APPROVAL -> ACTION -> VERIFICATION -> AUDIT -> COMPLETED`; plus `FAILED`, `DENIED`, `CANCELLED`
(terminal states are a PROPOSED ASSUMPTION). Shortcuts: `EVIDENCE->PLAN` only if research is disabled; `POLICY->ACTION` only if no step needs approval;
`POLICY->DENIED` on any deny; `CANCELLED` only before `ACTION`. `APPROVAL->ACTION` needs, for every gated step, an APPROVED, unexpired approval whose
`bound_digest == ActionRequest.digest()`; the ToolGateway then consumes it (single use) at execution and re-checks policy itself.

## 2. How each agent consumes it
- **LR 04 (backend):** implement `RunStore`, `AuditLog` (hash chain optional), `ApprovalService`, and a real `PolicyEngine` over PostgreSQL / `contract.models`; FastAPI routers must return the `api_models` types and match `openapi.yaml` (map `ContractError` subclasses via `ERROR_CODES`). Wire adapters only in `app/main.py`. Develop first against `build_fake_stack()`.
- **LR 05 (frontend):** generate TS types from `openapi.yaml` (e.g. `openapi-typescript`); never import Python. Poll `GET /api/runs/{id}/timeline?after_seq=` until `terminal`; render by `event.step`/`type`; show `mocked: true` results as "simulated"; render intake forms from `WorkflowSummary.input_schema`; approval cards come from `RunResponse.approvals` (status `pending`).
- **LR 06 (agent engineer):** implement `RunEngine` ONCE in `app/runtime/engine.py` (model it on `contract/fakes/engine.py`, which is a test double), the Nebius `ModelGateway`, the `ToolGateway` (+ Tavily `ResearchProvider` as a READ tool `web_search`), `Verifier`; author workflows as `WorkflowDefinition` in `app/workflows/<id>/definition.py`; call `validate_workflow_against_tools` at startup; every state change via `apply_transition`.
- **LR 07 (QA/eval):** run `packages/contract/tests` in CI; write conformance tests that run the SAME scenarios against `build_fake_stack()` and the real stack (`tests/`); run `python -m contract.arch_check .` and the checklist below; eval datasets target `WorkflowDefinition`/`PlanProposal` outputs, with `MockModel` for deterministic CI and Nebius for the eval job.

## 3. Versioning and breaking changes
- `CONTRACT_VERSION` is semver, mirrored in `openapi.yaml info.version` and stored on every `RunRecord.contract_version`.
- **Minor/patch (0.x.y)**: additive only (new optional field, new endpoint, new event payload key, new fake). LR 03 bumps and announces.
- **Breaking** (removing/renaming a field, tightening a validator, new state or transition, changing digest inputs, changing an endpoint): **never edit locally.** Raise to LR 03 with: what, why, affected files/agents. LR 03 decides, bumps the version (pre-1.0: bump minor for breaking), regenerates `openapi.yaml`, updates fakes and tests, and notifies LR 04/05/06/07. CI test `test_openapi_has_no_drift_from_pydantic_models` fails on stale specs.
- Models are `extra="forbid"`: unknown fields fail loudly, which is intentional. Run records pin `workflow_version`.

## 4. Daily ONE-runtime architecture review checklist (LR 03 + LR 07; ~5 minutes)
1. `python -m contract.arch_check .` is clean (R1-R6) and `pytest packages/contract` is green.
2. **No second orchestrator**: no new agent/graph/workflow framework, no loop that advances stages outside `app/runtime/engine.py`; `agents/`, `services/`, `tools/` still empty.
3. **No tool call outside ToolGateway**: no `httpx/requests/tavily` outside `runtime/tools/` + `model_gateway/`; every tool call carries `run_id`/`step_id`; Tavily is READ and only via `web_search`.
4. **No LLM call outside ModelGateway**: no provider SDK elsewhere; all model output is a pydantic schema (`complete_structured`), no free-text parsing; mock adapter impossible when `LIFERESCUE_ENV` is production/staging.
5. **No policy in prompts**: prompts (`intent.instructions`, `planning.instructions`) contain no allow/deny/approval rules; policy lives only in `WorkflowDefinition.policy` + `PolicyEngine`; default deny holds.
6. **State only via `apply_transition`**; no direct `run.state =` / SQL `UPDATE ... state`; no new state without a contract change.
7. **Approvals**: bound to action digest, single use, expiry; no code path executes a `mock_write` tool without `approval_id`; REAL_WRITE still rejected.
8. **Audit append-only**: no UPDATE/DELETE on audit tables; payloads redacted; secrets only via credential_broker/env, none in repo, logs, fixtures.
9. **Workflows are data**: `app/workflows/**` imports only `contract`; no `if workflow_id == ...` in runtime/api/web.
10. Untrusted text (user text, web pages, scam content) is passed as quoted data; no URL fetch outside a gated, SSRF-safe tool.

## 5. Deviations from proposed ADRs (sprint decisions win for the sprint; flagged, not silently changed — LR 03 to confirm)
- **ADR-0002 / ADR-0010**: one generic runtime + `WorkflowDefinition` instead of a LifeRescue-only orchestrator; ScamShield/LifeOS are workflows, not separate runtimes.
- **ADR-0003**: run state machine = brief's generic pipeline (+ FAILED/DENIED/CANCELLED), not the incident state machine; no per-incident state table.
- **ADR-0004**: generic `run / timeline / approvals / evidence / audit` models replace the incident-centric schema (`incident_id` -> `run_id`); persistence mapping left to LR 04.
- **ADR-0005 / ADR-0006**: policy = declarative first-match rules, default deny, version = content hash; approval TTL default 900 s (assumption); no operator role (single demo user, no auth).
- **ADR-0007 / ADR-0013**: Nebius-only holds; a `mock` model adapter is permitted for dev/tests with a config guard (blocked in production/staging).
- **ADR-0008**: tool contract reduced to side-effect classes `read | mock_write` (`real_write` reserved and rejected in 0.x); Tavily is a READ tool behind ToolGateway.
- **ADR-0009**: audit hash chain included as an assumption; timeline and audit are separate streams written together.
- **ADR-0014**: no event bus; timeline by polling over PostgreSQL (SSE deferred).
- **Stack (hosting/frontend deferrals in earlier ADRs)**: Next.js + FastAPI + PostgreSQL set by Ojas for the sprint.
- **Repo layout**: `infrastructure/` kept (not `infra/`); `packages/contract/` added; `agents/ services/ tools/` frozen empty.

## 6. Other assumptions (PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL)
Owner `demo-user`, no auth; polling not SSE; no `GET /api/runs` list endpoint and no memory spec in 0.1; `/api/health`; REAL_WRITE rejected; cancel only before ACTION;
a failed action tool becomes an error result and verification fails the run; `tool_result_status` passes if the tool was never called; unresolved research placeholders are skipped; `workflow.version` field added so runs pin definitions.

## 7. Run it
`python -m venv .venv && . .venv/bin/activate && pip install -e 'packages/contract[dev]' && pytest packages/contract && openapi-spec-validator packages/contract/openapi.yaml`
