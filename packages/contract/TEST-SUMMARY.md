# TEST-SUMMARY — platform contract 0.1.0 (run 2026-10-04 09:28 IST)

Env: Python 3.13.5, pydantic 2.13.5, pytest 9.1.1, openapi-spec-validator 0.9.0, mypy 2.4.0 (strict + pydantic plugin). Also verified: clean venv `pip install -e '.[dev]'` then pytest.

| Check | Result |
|---|---|
| `pytest -q` (tests/) | **215 passed, 0 failed** (~0.8 s) |
| `openapi-spec-validator openapi.yaml` | **OK** (OpenAPI 3.1.0); drift test: file == regenerated from pydantic models |
| `mypy contract` (strict) | **Success: no issues found in 23 source files** |
| Secret scan (ghp_, github_pat_, sk-<20+>, eyJ JWT, PRIVATE KEY, AKIA, tvly-, promo-code pattern, key/password/token string assignments) | **0 findings** (tests use obviously fake values, e.g. `sk-secret-value`, to prove redaction) |
| `contract.arch_check` on its own tree (as packages/contract) | clean (R1-R6) |

Test files: test_workflow_definition (schema + all validators + input validation), test_state_machine (every illegal pair, cancel window, policy and approval gating: pending/denied/consumed/expired/wrong-digest/changed-action/missing-step), test_interfaces_fakes (protocol conformance, default-deny, single-use + digest-bound approval, expiry, audit hash chain tamper detection, optimistic concurrency, mock-adapter production guard, redaction), test_smoke_run (full run through all 9 pipeline states with approvals; deny; cancel; policy deny; read-only plan skips approval; invalid model plans fail; failed verification fails; research placeholder skip; bad input; injection text), test_openapi, test_arch_check.

Reproduce: `cd packages/contract && pytest && openapi-spec-validator openapi.yaml && mypy contract`
