# apps/api - LifeRescue backend (FastAPI)

One generic workflow runtime behind one API for LifeRescue (vehicle breakdown), ScamShield (scam investigation) and
LifeOS (life admin). Jira: KAN-19. Ownership: scaffold, DB, routers, RunStore, AuditLog, ApprovalService,
PolicyEngine = LR 04; `app/runtime`, `app/verification`, `app/workflows/*` definitions = LR 06.

The API implements **platform contract 0.1.0** (frozen by LR 03, vendored verbatim in
[`packages/contract/`](../../packages/contract/CONTRACT-README.md)). Do not edit the contract here; change requests go
to LR 03. The spec of record is [`packages/contract/openapi.yaml`](../../packages/contract/openapi.yaml);
[`openapi.json`](openapi.json) is what this app actually serves (a test checks that every contract path/operation
exists in it). Endpoint notes: [docs/api.md](docs/api.md).

Python 3.11+ (developed on 3.13). Commands run from the repository root unless noted.

## Quick start

```bash
python3 -m venv apps/api/.venv && . apps/api/.venv/bin/activate
pip install -e packages/contract -e "apps/api[dev]"      # or: pip install -r apps/api/requirements.lock.txt

docker compose -f apps/api/docker-compose.yml up -d       # postgres:17 on 127.0.0.1:5432 (dev-only credentials)
export DATABASE_URL=postgresql://liferescue:liferescue_dev@localhost:5432/liferescue
(cd apps/api && alembic upgrade head)                      # runs, run_events, approvals, evidence, audit_log (+triggers)

# Server with the REAL SQL stores and a deterministic FAKE runtime (contract ReferenceRunEngine + fakes) - dev only:
(cd apps/api && LIFERESCUE_ENV=local LIFERESCUE_MODEL_ADAPTER=mock uvicorn tests.dev_app:app --port 8000)

# Production composition (app/main.py). Without LR 06's engine it uses a placeholder that only creates the run at INTENT:
(cd apps/api && LIFERESCUE_ENV=local LIFERESCUE_MODEL_ADAPTER=mock uvicorn app.main:create_app --factory --port 8000)
curl localhost:8000/api/health ; curl localhost:8000/api/workflows
```

No Docker? Any PostgreSQL 14+ works; `postgresql://` URLs are rewritten to the psycopg v3 driver.

## Composition root (`app/main.py`)

The only place adapters are wired (contract R-rules, checked by `python -m contract.arch_check .`). At startup it:
calls `assert_model_adapter_allowed` (fails closed: default env is `production`, default adapter `nebius`; `mock` is
refused outside local/test/ci), requires `NEBIUS_API_KEY` to be *present* for nebius (value never read here),
validates workflow schemas, then builds `Ports(settings, registry, SqlRunStore, SqlAuditLog, SqlApprovalService,
DeterministicPolicyEngine, redactor, clock)`. The run engine is picked in this order: `run_engine_factory` argument
(tests), else `app.runtime.wiring.build_engine(ports)` if LR 06 ships it, else the `PlaceholderRunEngine`.
`contract.fakes` / `contract.fixtures` are imported only from `tests/` (arch rule R3).

## Configuration (environment only)

| Variable | Default | Notes |
|---|---|---|
| `LIFERESCUE_ENV` | `production` | `local`/`test`/`ci` allow the mock adapter and `/docs`; anything else is treated as prod |
| `LIFERESCUE_MODEL_ADAPTER` | `nebius` | `nebius` or `mock` (mock only outside production) |
| `DATABASE_URL` | local compose Postgres | `postgresql://...`, `postgresql+psycopg://...` or `sqlite://` (tests) |
| `NEBIUS_API_KEY` | unset | env only, read only in `app/security/keys.py`; never in Settings, logs, DB or responses |
| `CORS_ORIGINS` | localhost:3000 | comma-separated or JSON list; `*` is rejected |
| `LOG_LEVEL` | `INFO` | JSON logs on stdout, redacted |

## Tests

Default run needs **no external services** (in-memory SQLite, no network):

```bash
cd apps/api && python -m pytest -q
```

Against real PostgreSQL (schema built by the real Alembic migration; tables truncated between tests; the DB name must
contain `test`, else the run aborts). This also enables the concurrency test and the least-privilege-role test:

```bash
docker compose -f apps/api/docker-compose.yml up -d
cd apps/api && DATABASE_URL=postgresql://liferescue:liferescue_dev@localhost:5432/liferescue_test python -m pytest -q
```

Contract package checks (also what CI should run for `packages/contract`):

```bash
pytest packages/contract -q && openapi-spec-validator packages/contract/openapi.yaml && python -m contract.arch_check .
```

## Lint, types

```bash
cd apps/api && ruff check . && ruff format --check . && mypy app tests   # mypy_path points at ../../packages/contract
python scripts/export_openapi.py          # regenerate openapi.json (a test fails if it is stale)
```

## Layout

```
app/main.py              composition root (create_app)
app/settings.py          pydantic-settings (no secrets)
app/errors.py            contract ERROR_CODES -> HTTP; body {"error": code, "message": text}
app/api/                 routers: health, workflows, runs; middleware (body limit, headers, request id)
app/db/                  SQLAlchemy models, SqlRunStore, DDL (audit_log triggers + grants), event allowlist
app/audit/sql_audit.py   SqlAuditLog (append-only, SHA-256 hash chain = PROPOSED ASSUMPTION)
app/approvals/           SqlApprovalService (atomic compare-and-set, digest-bound, TTL 900 s)
app/policy/engine.py     DeterministicPolicyEngine (default deny)
app/security/keys.py     ONLY reader of API keys / credential-broker adapter + layered redactor
app/workflows/           registry + seeded definitions (LR 06 owns the contents)
alembic/                 migrations (0001_initial)
tests/                   unit + API tests; dev_stack.py / dev_app.py compose the fakes (R3: tests only)
```

## Security notes (SECURITY-REQUIREMENTS ids in PR-DESCRIPTION.md)

- Secrets only via environment; nothing real is committed; `docker-compose.yml` has a throwaway local DB password.
- Error bodies never echo submitted values or exception text. Stored events/input/evidence/approvals are redacted at
  write time; timeline payloads are allowlisted per event type.
- `audit_log` is append-only: interface has no update/delete, DB triggers reject UPDATE/DELETE/TRUNCATE, the app role
  `liferescue_app` has only SELECT+INSERT on it, and the hash chain makes edits detectable.
- **Identity is a placeholder** (`X-Actor-Id`, default `demo-user`); there is no authentication (contract assumption).
- Known limitation: store methods are `async` but use blocking sync SQLAlchemy sessions.
