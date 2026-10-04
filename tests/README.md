# tests/

**Purpose:** cross-service tests: integration, end-to-end, agent evaluation, failure-injection and security tests (doc 19 Step 9 and Step 14; doc 20 Phase G).

**Source:** doc 19 Step 2 (directory skeleton); doc 19 Steps 9 and 14.

**Status:** contains [`security/`](security/README.md) (KAN-45 secret-management slice tests), and `conformance/` and `fixtures/` (LR 07, KAN-19). `tests/e2e` and `tests/eval` do not exist yet. Unit tests normally live next to the code they test.

## Where tests live (decision LR 01, 2026-10-04)
| Kind | Location |
|---|---|
| package-level tests | stay in their package: `packages/contract/tests`, `apps/api/tests` |
| cross-cutting conformance (same scenarios on the fake stack now, the real stack later) | `tests/conformance` |
| end-to-end and evaluation runs | `tests/e2e`, `tests/eval` (planned, not created) |
| security tests of the secret-management slice (KAN-45) | `tests/security` (exists on main; run it as its own step) |
| shared synthetic fixtures (Tavily-style replies, canned model outputs, golden cases, fake secrets) | `tests/fixtures` |

`tests/pytest.ini` and `tests/conftest.py` are the only pytest configuration for this tree; package tests keep their own.

## Run
```
python -m venv .venv && . .venv/bin/activate
pip install -e 'packages/contract[dev]'          # or just put packages/contract on PYTHONPATH (tests/pytest.ini already does)
pytest tests                                      # LR_STACK=fake (default): contract.fakes.build_fake_stack() wiring
LR_STACK=real pytest tests                        # real stack is not wired yet: stack tests are SKIPPED with a reason
python -m contract.arch_check .                   # ONE-runtime import rules R1-R6 (R3: contract.fakes only from tests/)
python tests/fixtures/validate_fixtures.py        # fixture sanity (also run as a test)
```
A CI job for this is proposed to LR 10 (not added here; `.github/` belongs to LR 10): install `packages/contract`, then `pytest packages/contract/tests`, `python -m contract.arch_check .`, `pytest tests`.

## What `tests/conformance` asserts
`happy path`, `policy deny` (default-deny, explicit deny, one denied step denies the plan, REAL_WRITE refused, unlisted tool/action type fail closed), `cancel`, `approval expiry`, `digest tamper`, `approval reuse` (single use, run-bound, decision-bound), the **approval rule** (every `mock_write` needs human approval; `web_search`/`safe_fetch` READ tools are policy-checked and audited but need none), `verification after action`, `audit complete` (hash chain, who decided, approval before every write), `redaction`, `fixtures`, and stack selection.

## Tests marked `xfail(strict=True)` (known gaps, flip when fixed)
* `test_redaction_gap.py` (29): **finding F3**, redaction is key-name based, so a secret typed into free text is stored and forwarded verbatim (run input, evidence, model prompt, timeline echo, plan params, approval summary, validation errors). Reason strings cite F3 / F6 / F8. When redaction improves these XPASS, strict mode fails the run, and the marker must be removed.
* `test_approval_rule.py::test_workflow_cannot_opt_out_of_mock_write_approval` (1): **finding G1**, `approvals.required_for_side_effects=[]` plus an ALLOW rule for `mock_write` is accepted by the contract and the write then runs without any approval.

## Adding a real-stack run
Implement `RealStack` in `tests/lr_support/stack.py` with the same method names as `FakeStack` (the surface section in its docstring), keep the `supports_*` flags false for things only a fake can do (clock control, store tampering, tool replacement). The tests then run unchanged.
