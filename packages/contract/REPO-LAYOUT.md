# REPO-LAYOUT — frozen for the product sprint (contract 0.1.0)

Owner: LR 03 Architect. Status: **FROZEN** at contract 0.1.0 (amend only via LR 03). Base: LR 01's layout in `PRODUCT-SPRINT-BRIEF.md`, against repo `main` @ `544bc4c`.
Anything marked **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** is a choice the brief left open.

## 1. Layout

```
/
├─ packages/
│  ├─ contract/                 # THIS contract (import name `contract`) — LR 03
│  │   ├─ contract/             #   models, workflow_definition, run_state_machine, interfaces, api_models, validation, arch_check
│  │   │   ├─ fakes/            #   in-memory test doubles (tests/dev servers ONLY)
│  │   │   └─ fixtures/         #   vehicle_breakdown example (tests ONLY)
│  │   ├─ tests/  openapi.yaml  pyproject.toml
│  └─ credential_broker/        # KAN-45 (existing) — LR 04
├─ apps/
│  ├─ api/                      # FastAPI — LR 04 (scaffold, DB, endpoints), see §2
│  │   └─ app/
│  │       ├─ main.py           #   composition root: wires adapters into ports, the ONLY place that does so — LR 04
│  │       ├─ api/              #   routers; call RunEngine + RunStore reads only — LR 04
│  │       ├─ db/               #   PostgreSQL: RunStore/AuditLog persistence, migrations — LR 04
│  │       ├─ runtime/          #   THE runtime: engine.py (RunEngine), model_gateway/ (Nebius adapter), tools/ (registry, ToolGateway, tavily.py, mock tools) — LR 06
│  │       ├─ policy/           #   PolicyEngine implementation (deterministic) — LR 04
│  │       ├─ approvals/        #   ApprovalService implementation — LR 04
│  │       ├─ audit/            #   AuditLog implementation — LR 04
│  │       ├─ verification/     #   Verifier implementation — LR 06
│  │       └─ workflows/<id>/   #   definition.py ONLY: vehicle_breakdown, scam_investigation, life_admin — LR 06
│  └─ web/                      # Next.js — LR 05
├─ tests/                       # e2e, eval, conformance, architecture checks — LR 07
├─ infrastructure/              # docker-compose, deploy — LR 10 (only LR 10 edits .github/workflows)
├─ docs/                        # ADRs and docs — LR 03 / LR 08 via PR
└─ agents/ services/ tools/ scripts/   # skeleton dirs from main: NO product code (see changes)
```

## 2. Changes to LR 01's proposal (1 line each)

1. `infra/` -> **`infrastructure/`**: that directory already exists on `main`; no rename churn. CI stays in `.github/workflows` (LR 10 only).
2. **Added `packages/contract/`**: one shared, dependency-free package so api, web (via OpenAPI), tests and fakes agree on one schema.
3. **`apps/api/app/main.py` is the single composition root**: ports are wired to adapters in one place, so swapping fake/real is one file.
4. **`apps/api/app/api/` and `app/db/` added** (not in the brief): separates HTTP and persistence from the runtime so `runtime` imports neither.
5. **`agents/`, `services/`, `tools/` are frozen empty**: they invite a second orchestrator or a second tool path; tools live only under `runtime/tools/`.
6. **`apps/api/app/workflows/<id>/` holds `definition.py` only** (data, no logic) so a workflow is config, never code.
7. **`packages/credential_broker` stays as is**; it is the only place (with the Nebius/Tavily adapters) that reads `NEBIUS_API_KEY` / `TAVILY_API_KEY`.

## 3. Ownership (who may change what; CODEOWNERS today is `* @ojas005`, this table is the working agreement — PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL)

| Path | Owner | Reviewer / notes |
|---|---|---|
| `packages/contract/**` | LR 03 | nobody else edits; change requests go to LR 03 (see CONTRACT-README §3) |
| `apps/api/` scaffold, `app/main.py`, `app/api/`, `app/db/`, `app/policy/`, `app/approvals/`, `app/audit/`, `packages/credential_broker/` | **LR 04 (backend)** | policy rules semantics reviewed by LR 03 |
| `apps/api/app/runtime/**`, `app/verification/`, `app/workflows/**` | **LR 06 (agent engineer)** | the `policy` and `approvals` blocks inside a `definition.py` need LR 04 + LR 03 review (policy is deterministic code-config, not prompt) |
| `apps/web/**` | **LR 05 (frontend)** | consumes `openapi.yaml` only (no Python imports) |
| `tests/**` (e2e, eval, conformance, architecture) | **LR 07 (QA/eval)** | may read everything; edits no product code |
| `infrastructure/**`, `.github/workflows/**` | LR 10 | |
| `docs/**` | LR 03 (architecture), LR 08 (advisory) | PRs only |

## 4. Import / dependency rules (what makes it ONE runtime)

Dependency direction (arrows = "may import"); anything not listed is forbidden:

```
contract  <──  app.runtime, app.policy, app.approvals, app.audit, app.db, app.verification, app.api, app.workflows, tests
app.api  ──>  contract.api_models; the RunEngine PORT; RunStore reads         (never tools, models, policy directly)
app.runtime ─> contract ports only (ModelGateway, ToolGateway, PolicyEngine, ApprovalService, Verifier, AuditLog, RunStore)
app.workflows.* ─> contract.workflow_definition / contract.models only        (no `app.*`, no I/O libs)
app.policy | approvals | audit | db  ─/─> app.runtime   (no back-edges)
app.main ──> everything (composition root)
```

Hard rules (checked by `python -m contract.arch_check <repo_root>`, rules R1-R6, and by LR 07 in CI):
- **R1** No second orchestrator/agent framework (langgraph, langchain, crewai, autogen, llama_index, ...). The only orchestrator is `app/runtime/engine.py` implementing `contract.interfaces.RunEngine`.
- **R2** LLM and network client libs (openai, tavily, httpx, requests, ...) are imported only in `runtime/model_gateway/`, `runtime/tools/`, `packages/credential_broker/`.
- **R3** `contract.fakes` / `contract.fixtures` are imported only by tests (and dev stubs under `tests/`). Production composition never imports them; the mock model is blocked by `assert_model_adapter_allowed` when `LIFERESCUE_ENV` is production/staging.
- **R4** Workflows are data: `app/workflows/**` imports only `contract`.
- **R5/R6** `runtime` does not import `app.api` or `app.db`; policy/approvals/audit/db do not import `runtime`.
- Only `run_state_machine.apply_transition` sets `RunRecord.state`. Next.js talks to FastAPI only through `/api/*` (generate TS types from `openapi.yaml`); it never calls Nebius/Tavily.
