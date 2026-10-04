# Secrets and credentials: the KAN-45 mock slice

**Status: PROPOSED. MOCK-ONLY.** This page documents the code in [`packages/secrets/`](../../packages/secrets/README.md) and the tests in [`tests/security/`](../../tests/security/README.md). It was written by LR 04 (Backend Engineer) from the LR 08 spec (`bootstrap/analysis/security-drafts/specs/KAN-45-secret-management-slice-spec.md`). Nothing here is approved policy until a human merges it. Anything marked **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** is a decision the spec did not make.

There is no real secret manager, no real credential and no network or file access in this slice. The product choice (a real secret manager) is deferred.

## 1. Model in one paragraph

An agent never holds a credential. It asks the broker for a **lease** and receives a **handle** (an opaque id with no value). A **gateway** (identified by a registered, hidden gateway identity) presents the handle together with the acting task, run and agent, and uses the value inside `with secret.reveal() as raw:` for the duration of one provider call. The value is wiped when the block ends. Leases are short, task-scoped and revoked when the task ends. Every state change produces exactly one audit event that carries identifiers and shapes only.

Defence order (from the spec): prevent by type and construction, then redact, then scan.

## 2. Invariants and where they are enforced

| # | Invariant | Enforced by | Tests |
|---|---|---|---|
| I-1 | A secret value never prints, formats, pickles, copies or serialises | `SecretValue` (`secret_types.py`) | T-02 |
| I-2 | Deny by default; only names listed in the policy can be leased | `policy.py`, `broker.request` | T-03, T-04 |
| I-3 | A handle works only for the task, run and agent it was issued to, and only for a registered gateway | `broker.use`, `CallContext`, `GatewayIdentity` | T-08, T-09 |
| I-4 | Task end revokes every lease of the task | `tasks.py`, `broker.revoke_task` | T-07 |
| I-5 | `PRODUCTION` is always refused | constant check in `broker.request`, rejected by config, policy loader and constructor | T-14 |
| I-6 | Audit events and logs carry allow-listed, shape-checked fields only | `audit.py`, `logging_rules.py` | T-18, T-30 |
| I-7 | Any internal fault fails closed (no credential issued) | `broker.py` | T-13, T-29 |
| I-8 | A leased value cannot leave through a log, exception, prompt, database write, outgoing text or response to an agent | `redaction.py`, `guards.py` | T-16 to T-21, T-23 |

## 3. Configuration (all PROPOSED defaults, none hard-coded policy)

See the table in [`packages/secrets/README.md`](../../packages/secrets/README.md). They are `BrokerConfig` fields (`from_mapping` or `from_json_file`); the code never reads the environment. Expiry uses a monotonic clock; wall-clock time is recorded for audit only, so clock jumps do not extend or shorten a lease (T-29). A TTL above the maximum is **denied, not clamped** (**PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**; the spec says "denied or clamped").

## 4. Redaction

Redaction is the second layer. It is implemented in `redaction.py` and applied by `guards.py`.

**Known-value redaction.** The set of currently leased values is held in memory (`leased_values.py`). For each value the redactor matches the exact text and these derived forms: base64 (standard and URL-safe, at all three alignments), URL-encoding, JSON, Python repr, unicode and HTML escapes, hex, backslash-escaped, and the value **split across whitespace, quotes, backslashes or a `+`** (a generated regex). Variants other than the exact value apply only to values of at least 8 characters. Result marker: `[REDACTED:secret]`.

**Pattern redaction.** `patterns.json` holds 13 rules. Seven mirror the rule ids of the proposed `.gitleaks.toml` (xAI, NVIDIA, Tavily, Atlassian, Nebius assignment, URL-embedded password, private-key file reference); six are Python-only extras (private key block of any type, bearer token, authorization header, cookie, secret in URL query, generic `password=`-style assignment). Result marker: `[REDACTED:<kind>]`.

**Key-name rule.** In any mapping, a value whose key contains `password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, `authorization`, `cookie`, `set_cookie`, `private_key`, `credential` or `connection_string` is replaced by `[REDACTED:field]` whatever it contains. Keys are normalised (`X-Api-Key`, `dbPassword` match). This **over-redacts on purpose**, for example `max_tokens` or `token_metadata`; use the explicit `key_exempt` argument for reviewed exceptions rather than loosening the rule.

**Structures and exceptions.** Nested dicts, lists, tuples and sets are walked (depth limit, cycle-safe). Unknown object types are replaced by `[REDACTED:object]` rather than formatted. Exceptions are redacted along their whole `__cause__` / `__context__` chain, and so are formatted tracebacks. Input larger than the size limit fails closed.

### Sink guards (`guards.py`)

| Guard | Behaviour on a hit |
|---|---|
| `prompt(content)` | raises `SecretLeak`, emits a `redaction_blocked` event, and refuses the same content if it is tried again (no retry with the same text) |
| `persist(record, write)` | refuses the whole write; `write` is not called |
| `outgoing(text)` | refuses (does not redact): a message sent to Jira, a PR or chat cannot be unsent (**PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**) |
| `return_path(response)` | returns the redacted structure |
| `run_provider_call(call)` | success: redacted result; failure: a redacted error result, never a raised provider error body |
| `RedactingLogFilter` | redacts message, arguments, extra fields and exception text of a `logging` record |
| `RedactingAuditSink` | scrubs any string field that contains a leased value before it is stored |

The broker wraps its audit sink automatically. `broker.redact(...)`, `broker.assert_safe_to_emit(...)` and `broker.assert_safe_to_emit_obj(...)` are the checks the guards use.

## 5. Logging, audit and metrics

* Only allow-listed fields are logged for credential events; unknown keys are dropped and the key name is not logged. Free-form records on the credential logger are dropped.
* Audit event types (9): `lease_requested`, `lease_denied`, `lease_issued`, `lease_used`, `lease_expired`, `lease_revoked`, `redaction_blocked`, `misuse_suspected`, `backend_unhealthy`. Fields are shape-checked; an invalid field becomes `invalid`. Events carry an `alert` flag (**PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**) for the cases the spec says should raise an alert signal.
* Exceptions are exported as a class name only. There is no OpenTelemetry integration in this slice; `telemetry.py` provides the sanitising functions an exporter would call.
* `metrics.py` holds simple in-process named counters (with an optional label), for example per denial reason and per redaction sink.

## 6. Rules for gateway authors (when real gateways exist)

1. Call `reveal()` only inside the provider call, and never assign the revealed text to a variable that outlives the `with` block.
2. Never put a value, or a string derived from it, into a return object, exception message, log call, metric label or trace attribute. Wrap provider calls in `guards.run_provider_call`.
3. Build model prompts only from text that passed `guards.prompt`. Write to a database or checkpoint only through `guards.persist`.
4. Do not widen the key-name exemptions to make a test pass; ask the security owner.
5. Host code must call `broker.maybe_sweep()` regularly; the broker starts no thread of its own.

## 7. Backend conformance

`conformance.py` provides `BackendConformanceMixin` (T-27). A future real backend subclasses it in its own test module and must pass the same contract (hard TTL, revocation, unknown references, no value in errors, health, no `PRODUCTION`). Seven deliberately broken backends are used in `tests/security/test_backend_conformance.py` to prove the suite detects each defect.

## 8. Pattern parity and tests of the tests

* **Parity (T-22).** `parity.py` loads the rules of a `.gitleaks.toml`, generates a random corpus of positive and negative samples per rule, and compares the scanner's regex with the redactor's. In this repository the real file is not yet present, so the test of the real config is **skipped** unless `<repo>/.gitleaks.toml` exists or `KAN45_GITLEAKS_CONFIG` points to a file. The harness itself is tested against a generated mirror and against deliberately drifted copies. Differences between the scanner's regex engine and Python's `re` are possible; the corpus is the guard, not a proof.
* **Self-scan (T-26).** `test_repo_scan.py` applies the scanner-mirrored patterns to the package, tests and docs; it also proves it can find a planted value.
* **Mutation check.** `python3 tests/security/mutation_check.py -v [--gitleaks-config PATH]` breaks one guard at a time in a temporary copy and requires a named test to fail. See [`tests/security/README.md`](../../tests/security/README.md).
* **No realistic credential is committed.** Canaries are generated at test runtime with random characters and a non-provider prefix. Source literals that would look like a URL with an embedded password are assembled from parts.

## 9. Known limitations

* Known-value redaction covers only values that are **currently leased**. A value after revocation is no longer matched by value (patterns and the key-name rule still apply).
* The agent facade (`agent_client`) is request-only by construction, but it is an in-process object, not a sandbox. A hostile in-process agent could reach other objects; process isolation is a deployment concern.
* The key-name rule over-redacts (see section 4). Pattern rules for providers other than the five in the proposed `.gitleaks.toml` are not verified against real key formats.
* The regex engines differ (scanner versus Python); see section 8.
* Tested only on Python 3.13.5. The parity harness needs Python 3.11+ (`tomllib`).
* Running Python from inside `packages/` would let the package name `secrets` shadow the standard library module; run tests from the repository root.

## 10. Deferred (spec section 10) and not done

* A real secret manager, a TEST or real credential environment, and credential rotation.
* The ADR that chooses the secret manager and the interface confirmation by the architect (LR 03).
* **T-25, repository scan evidence in CI**, and wiring `tests/security` into CI. Workflows belong to LR 10; this slice does not touch `.github/workflows/`.
* `scripts/security/scan-paths.sh` and `.gitleaks.toml` (LR 08 drafts) are not in this repository yet.
* Auto-pausing an agent or revoking all its leases on suspected misuse (open question 3 in the spec).
* OpenTelemetry integration and a sweep thread.
