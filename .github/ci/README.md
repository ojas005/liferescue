# .github/ci/ - hash-locked Python tooling for CI

Owner: LR 10 (SRE/DevOps). Used by `.github/workflows/ci.yml` (jobs `contract-tests`, `arch-check`, `dependency-audit`).

| File | Purpose |
|---|---|
| `contract.in` | inputs for the `packages/contract` CI environment: the package's declared ranges, plus CI-only `ruff` and `setuptools` |
| `contract-requirements.txt` | **lock**: exact versions and sha256 hashes of everything in `contract.in` (universal for Python 3.11-3.14) |
| `audit.in` / `audit-requirements.txt` | same for `pip-audit` (used only by the report-only `dependency-audit` job) |

Jobs install with `pip install --require-hashes --no-deps -r .github/ci/<lock>`, so a changed or tampered wheel fails the install. Nothing runs an unpinned `pip install <name>`.

## Regenerate (when a dependency of packages/contract or a tool version changes)

```bash
cd .github/ci
uv pip compile --universal --python-version 3.11 --generate-hashes contract.in -o contract-requirements.txt
uv pip compile --universal --python-version 3.11 --generate-hashes audit.in    -o audit-requirements.txt
```

Review the diff (versions only should move), run the `contract-tests` commands locally, commit both files. `pip check` in the job fails when `packages/contract/pyproject.toml` declares a range the lock does not satisfy; update `contract.in` and regenerate in that case.

## What each per-package job does

`contract-tests` (matrix Python 3.11-3.14), only when `packages/contract/pyproject.toml` exists: pytest in `packages/contract` (JUnit report; at least 215 passed, see `MIN_CONTRACT_TESTS`), `mypy --strict contract`, `ruff check --isolated --select E9,F63,F7,F82` (blocking), full `ruff check` + `ruff format --check` (**report-only** while `RUFF_FULL_BLOCKING: "false"`: PR #18's package is not ruff-clean, so enforcing it would make `CI gate` red on a change that is not CI's to make), and `openapi-spec-validator openapi.yaml` (the pytest suite also fails on drift between `openapi.yaml` and the pydantic models).
`arch-check`, same condition: `python -m contract.arch_check .` from the repository root (rules R1-R6).
`security-corpus`: `scripts/ci_corpus_check.py` runs each `corpus_selfcheck.py` found next to `ssrf-urls.json` / `injection-corpus.json`.
`dependency-audit`: `pip-audit` over every tracked `requirements*.txt` (including the locks above) and `npm audit` over every tracked `package-lock.json`; findings are logged and summarised, never blocking.

## Adding another package

1. Add a `detect` output for its explicit path in `ci.yml`, a job bound to it (`needs: detect`, `if: needs.detect.outputs.<name> == 'true'`) and an entry in `CONDITIONAL` in `scripts/ci_gate.py`; add the job to `ci-gate` `needs`.
2. Add its inputs/lock here, and tests to `scripts/test_ci_helpers.py` (gate) and `scripts/test_workflow_guards.py`.
3. Keep `CI gate` the only required check.

## Not covered (by design, today)

- `apps/api`, `apps/web`: scaffolds are pending; `detect` lists unclaimed `pyproject.toml` / `package.json` files in the job summary. A Node job for `apps/web` is deliberately not included.
- `packages/secrets` (old name, rename pending): not type-clean in isolation (`mypy`: 10 errors even without `--strict`), so it has no job of its own; its tests run in `python-unit-tests` (`tests/security`).
- Product-level SSRF (`safe_fetch`) and injection-invariant tests (LR 07 `SEC-*`): they do not exist on `main`. `security-corpus` only proves corpus self-consistency.
- SBOM, build, artifact, container scan, deployment.
