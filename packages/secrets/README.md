# packages/secrets/

**Status: MOCK-ONLY slice (Jira KAN-45).** In-memory backend with randomly generated values that exist only for a test run. There is **no real secret manager, no real credential, no network, no file or environment access** in this package. The product choice for a real secret manager is deferred (spec section 10; ADR pending).

**Source:** `bootstrap/analysis/security-drafts/specs/KAN-45-secret-management-slice-spec.md` (LR 08, PROPOSED). Everything here is a **PROPOSED** implementation for human review; nothing is approved until Ojas merges it.

## Principle

The agent holds a **handle**, the gateway holds the **value**, and only for the duration of one call. Prevent by type and construction first, redact second, scan third.

## Layout (this PR: spec steps 1 to 4)

| Module | Purpose |
|---|---|
| `codes.py` | Closed lists of request, denial and revocation reason codes (no free text anywhere). |
| `errors.py` | Exceptions. Messages are fixed strings or codes; they never carry values. |
| `secret_types.py` | `Environment`, `Purpose`, `SecretRef`, `SecretValue`, `CredentialRequest`, `LeaseHandle`, `LeaseState`, `CallContext`, `GatewayIdentity`, `ScopedSecret`. |
| `config.py` | `BrokerConfig`: TTLs, limits and rate limits as **configuration values with documented defaults**. |
| `policy.py`, `policy.json` | Deny-by-default grants (names and limits only, never values). JSON, not YAML (stdlib only). |
| `clock.py` | Clock protocol; monotonic time enforces expiry, wall time is recorded for audit. |
| `backend.py`, `memory_backend.py` | `SecretBackend` protocol and the in-memory MOCK backend. |
| `tasks.py` | Task-liveness protocol and an in-memory mock registry. |
| `audit.py`, `metrics.py` | Audit event contract and sinks; counters. |
| `logging_rules.py`, `telemetry.py` | Logging and telemetry allow-lists. |
| `broker.py`, `agent_api.py` | `CredentialBroker` (request/use/revoke/sweep) and the request-only agent facade. |
| `testing.py` | Reusable helpers: random canary generator, `FakeClock` (for KAN-46). |

The redaction library, sink guards, pattern parity harness, conformance suite and docs arrive in the second PR (spec steps 5 to 8).

## Configuration and defaults

All numbers below are **PROPOSED defaults from the spec, not policy**. They live in `BrokerConfig` and can be changed without code edits (`BrokerConfig.from_mapping` / `from_json_file`). Nothing reads the environment.

| Field | Default | Meaning |
|---|---|---|
| `default_ttl_seconds` | 900 (15 min) | TTL when a request gives none |
| `max_ttl_seconds` | 1800 (30 min) | global maximum for MOCK and TEST |
| `max_ttl_real_credential_seconds` | 3600 (60 min) | reserved for a future real credential; **unused** here because no real environment can be served |
| `max_leases_per_task` | 4 | concurrent leases per task |
| `max_uses_per_lease` | 200 | `use` calls per lease |
| `sweep_interval_seconds` | 30 | expired leases are dropped at most this long after expiry even if never used again |
| `agent_rate_limit_per_minute` | 30 | requests per agent per minute |
| `global_rate_limit_per_minute` | 300 | **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** (the spec asks for a global limit but gives no number) |
| `max_terminal_records` | 1000 | bounded metadata kept for expired/revoked leases (no values) |
| `served_environments` | `["mock"]` | `production` is rejected by a constant check, whatever the configuration |

## Hard rules enforced in code

* `Environment.PRODUCTION` is always refused (constant check in the broker, rejected in config and policy loaders, rejected at startup if a backend declares it).
* Deny by default; any internal failure (policy invalid, backend down, clock fault, task registry unavailable) fails closed with an audit event and an alert flag.
* No exception or audit event carries request content or a value.

## Running the tests

From the repository root (not from inside this directory; the name `secrets` would shadow the standard library):

```bash
python3 -m unittest discover -s tests/security -v
```

Requires Python 3.11+ (stdlib only; no third-party packages). CI wiring is not part of this slice (`.github/workflows/` is owned by LR 10).
