# Agent runtime (KAN-39, LR 06) — conforms to platform contract 0.1.0

Implements the contract's `RunEngine`, `ModelGateway`, `ToolGateway`, `ResearchProvider` and `Verifier`
**once**, domain-agnostic. Workflows are `WorkflowDefinition` data (`app/workflows/<id>/definition.py`,
added by LR 05/Day 4-7); nothing in the runtime knows about any specific workflow.

```
app/runtime/engine.py           WorkflowEngine (RunEngine): start / advance / decide_approval / cancel
app/runtime/model_gateway/      AIProvider (ModelGateway superset), MockAIProvider, NebiusProvider, provider_from_env
app/runtime/tools/gateway.py    RuntimeToolGateway (ToolGateway): validate -> policy -> approval -> execute -> audit
app/runtime/tools/safe_fetch.py the ONE SSRF-safe fetcher (S1-S6) used by READ tool `fetch_url`
app/runtime/tools/tavily.py     TavilyProvider (ResearchProvider) behind READ tool `web_search`
app/runtime/{untrusted,redaction,errors,events,memory}.py
app/verification/verifier.py    RuntimeVerifier (Verifier)
scripts/smoke_nebius.py         one-command live smoke (prints "key not provided", exit 0, if no key)
scripts/run_workflow_demo.py    end-to-end demo on the Mock provider (labelled MOCK)
```

## Wiring (composition root, e.g. `app/main.py`, owned by LR 04)

```python
provider = provider_from_env(workflow=None)            # AI_PROVIDER=mock|nebius (default nebius)
research = TavilyProvider()                            # key from TAVILY_API_KEY only
gateway  = RuntimeToolGateway(policy, approvals, audit)
register_web_search(gateway, research); register_fetch_url(gateway)
register_mock_write(gateway, "my_tool", "…", schema=MyParams)   # real_write is rejected at register()
engine = WorkflowEngine(registry=…, store=…, provider=provider, tools=gateway, policy=policy,
                        approvals=approvals, audit=audit, verifier=RuntimeVerifier(provider),
                        memory=…, event_sink=…, limits=RunLimits())
```

`WorkflowEngine.__init__` calls `validate_workflow_against_tools` for every registered workflow
(fail-fast at startup). LR 04 supplies `RunStore`, `AuditLog`, `ApprovalService`, `PolicyEngine`
(contract ports); the runtime uses them only through the contract Protocols. Everything is `async`
(FastAPI-friendly). `RunRecord.state` changes **only** via `contract.run_state_machine.apply_transition`.
Approval pause = run in `APPROVAL` state with a pending approval + `approval` event
(`payload.pending=True`); resume with `engine.decide_approval(run_id, approval_id, approved, decided_by)`.

Key via credential broker: `NebiusProvider(key_provider=lambda: broker.get("NEBIUS_API_KEY"))`
(default: env `NEBIUS_API_KEY`). Keys are never logged, stored or put in events (registered with the redactor).

## Provider selection / env

| var | meaning |
|---|---|
| `AI_PROVIDER` | `mock` \| `nebius` (fallback `LIFERESCUE_MODEL_ADAPTER`; default `nebius`) |
| `LIFERESCUE_ENV` | contract guard: `mock` is refused when `production` (the contract default!) — set `development` locally |
| `NEBIUS_API_KEY` | only source of the key; missing -> `NotConfigured` at first use ("key not provided") |
| `NEBIUS_BASE_URL` | default `https://api.tokenfactory.us-central1.nebius.com/v1/` (https only) |
| `NEBIUS_MODEL` | default `nvidia/nemotron-3-super-120b-a12b` |
| `NEBIUS_TIMEOUT_S` | per-call timeout |
| `TAVILY_API_KEY`, `TAVILY_DAILY_CAP` | research key / daily request cap (default 200) |

Endpoint notes: the brief's `api.studio.nebius.com` (AI Studio) is superseded by Nebius **Token Factory**
(`api.tokenfactory.nebius.com/v1/`); Nemotron-3-Super is documented under the us-central1 region host.
**Not verified live** (no key; Nebius account billing-blocked). Run `scripts/smoke_nebius.py` once a key exists.

## Timeline events (for LR 05 UI / LR 04 SSE)

Events are contract `TimelineEvent`s (`step` = stage `RunState`, `type` = `EventType`), payloads always redacted.
Every model-derived event (`run created`, `intent`, `plan`, `audit` summary) carries
`payload.provider = {adapter, model, label, mock}`; mock output is labelled `MOCK (scripted, not real AI)`.
Keys by type: `intent{summary,category,urgency,entities,tokens,latency_ms}`, `evidence{collected,missing}`,
`research{query,tool,status,result_count,source_urls,untrusted:true,tool_call}`, `plan{steps,summary,tokens}`,
`policy{step_id,tool,outcome,risk,rule_id,reason,action_digest}` (a failed plan check emits `policy` with
`code=schema_violation`), `approval{approval_id,status,risk,params,action_digest,simulated,pending}`,
`action{step_id,tool,status,mocked,label,output,error,tool_call}` (simulated actions are labelled SIMULATED),
`verification{checks,passed}`, `audit{audit_records,…}`, `error{code,…}`. Caps: terminal `FAILED` with
`terminal_reason="limit_reached: …"` and an `error` event `code=limit_reached`.

## Limits (U5) — `RunLimits` defaults
15 steps, 8 tool calls, 60 s wall time (per `advance()` segment), 40 000 tokens, 5 research queries,
30 s per model call. Counters are rebuilt from stored events so a resume cannot reset them.

## Security checklist mapping (SECURITY-REQUIREMENTS.md)
U1 untrusted-data boundary (`untrusted.py`, per-run random id, defanging, 8 KB cap) · U2 deterministic plan
validation (tool/action allowlist, step count, tool JSON-schema, extra fields, no looser retry) · U3 policy
outside the LLM, default-deny, fail-closed (`gateway.py`, engine catch-all) · U5 caps · S1–S6 one shared
`safe_fetch` (scheme/port/userinfo/IP-literal rules, DNS resolve + every address checked, pinned-IP connect with
Host/SNI, redirect revalidation, 3 s/8 s/1 MB limits, content-type allowlist) · T1 deny-by-default registry,
real_write rejected · T2 args validated against tool schema before policy · K2/K3 redaction of logs/events/errors,
httpx loggers at WARNING, secrets registered with redactor, PII masked before any model prompt (P2).

## Run it
```
cd apps/api
python -m pytest tests/runtime -q      # hermetic: no network, no keys
ruff format --check . && ruff check . && MYPYPATH=.:../../packages/contract mypy app
python scripts/run_workflow_demo.py    # Mock provider, labelled MOCK
python scripts/smoke_nebius.py         # live; "key not provided" without NEBIUS_API_KEY
python -m contract.arch_check <repo>   # PYTHONPATH=packages/contract
```
`packages/contract` must be present (LR 03's PR); override with `LIFERESCUE_CONTRACT_PATH`.
Dependencies: see `DEPENDENCIES.txt` (intentionally not a CI-activating requirements file).
