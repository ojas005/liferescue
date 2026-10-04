#!/usr/bin/env python3
"""Mutation check for the KAN-45 secret-management tests (spec T-24 spirit: test the tests).

For each mutation: copy ``packages/`` and ``tests/security/`` to a temp dir, remove or break ONE
guard with an exact text replacement, run the named test modules there, and require that they FAIL.
A mutation that survives (tests still pass) means a guard is not really tested; the script exits 1.
The working tree is never modified. Standard library only.

Usage (from the repository root):   python3 tests/security/mutation_check.py [-v]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Mutation:
    mutation_id: str
    path: str  # relative to repo root
    old: str  # must occur exactly once
    new: str
    tests: tuple  # test module file names under tests/security
    why: str


MUTATIONS = [
    Mutation("M01-production-check-removed", "packages/secrets/broker.py",
             "if req.ref.environment is Environment.PRODUCTION:", "if False:",
             ("test_broker.py",), "constant PRODUCTION refusal (T-14, I-5)"),
    Mutation("M02-config-allows-production", "packages/secrets/config.py",
             "if Environment.PRODUCTION in envs:", "if False:",
             ("test_config_backend.py",), "config must reject PRODUCTION (T-14)"),
    Mutation("M03-policy-accepts-production-grant", "packages/secrets/policy.py",
             "if env is Environment.PRODUCTION:", "if False:",
             ("test_policy.py", "test_broker.py"), "policy must reject a PRODUCTION grant (T-14)"),
    Mutation("M04-lease-never-expires", "packages/secrets/broker.py",
             "or mono < lease.expires_mono:", "or True:",
             ("test_broker.py", "test_audit_logging.py"), "TTL expiry (T-06)"),
    Mutation("M05-secretvalue-str-leaks", "packages/secrets/secret_types.py",
             "    def __str__(self) -> str:\n        return REDACTED", "    def __str__(self) -> str:\n        return self._decode()",
             ("test_secret_types.py", "test_broker.py"), "SecretValue must not print (T-02, I-1)"),
    Mutation("M06-secretvalue-pickle-allowed", "packages/secrets/secret_types.py",
             "    def __reduce_ex__(self, protocol):\n        raise TypeError(\"SecretValue cannot be pickled\")",
             "    def __reduce_ex__(self, protocol):\n        return (SecretValue, (self._decode(),))",
             ("test_secret_types.py",), "SecretValue must not pickle (T-02)"),
    Mutation("M07-context-check-removed", "packages/secrets/broker.py",
             "if (context.task_id, context.run_id, context.agent_id) != (lease.task_id, lease.run_id, lease.agent_id):", "if False:",
             ("test_broker.py",), "handle bound to task/run/agent (T-08, I-3)"),
    Mutation("M08-gateway-identity-not-checked", "packages/secrets/broker.py",
             "return hmac.compare_digest(expected.encode(), caller._token.encode())", "return True",
             ("test_broker.py",), "only registered gateways may use (T-09)"),
    Mutation("M09-revoke-task-noop", "packages/secrets/broker.py",
             "for lease in [l for l in self._leases.values() if l.task_id == task_id]:", "for lease in [l for l in self._leases.values() if False]:",
             ("test_broker.py", "test_audit_logging.py"), "task end revokes all leases (T-07, I-4)"),
    Mutation("M10-deny-by-default-removed", "packages/secrets/policy.py",
             "and ref.name in grant.names", "and True",
             ("test_policy.py", "test_broker.py"), "deny by default for unlisted names (T-03, T-04)"),
    Mutation("M11-duplicate-lease-allowed", "packages/secrets/broker.py",
             "if any(l.ref == req.ref for l in live):", "if False:",
             ("test_broker.py",), "one lease per (task, ref) (T-11)"),
    Mutation("M12-ttl-ceiling-removed", "packages/secrets/broker.py",
             "if ttl > ceiling:", "if False:",
             ("test_broker.py",), "TTL above maximum is denied (T-05)"),
    Mutation("M13-task-liveness-not-checked", "packages/secrets/broker.py",
             "        if not live:\n            raise _Refuse(DenialReason.TASK_NOT_LIVE)", "        if False:\n            raise _Refuse(DenialReason.TASK_NOT_LIVE)",
             ("test_broker.py",), "task must be live (spec 4.3 rule 4)"),
    Mutation("M14-clock-regression-ignored", "packages/secrets/broker.py",
             "elif self._last_mono is not None and mono < self._last_mono:", "elif False:",
             ("test_broker.py",), "clock fault fails closed (T-13, T-29)"),
    Mutation("M15-backend-health-ignored", "packages/secrets/broker.py",
             "if not self._backend_healthy():", "if False:",
             ("test_broker.py",), "backend down fails closed (T-13)"),
    Mutation("M16-audit-field-sanitising-removed", "packages/secrets/audit.py",
             "    return \"invalid\"", "    return value",
             ("test_audit_logging.py",), "audit fields are shape-checked (I-6)"),
    Mutation("M17-log-field-shape-check-removed", "packages/secrets/logging_rules.py",
             "out[key] = value if FIELD_SHAPES[key](value) else \"invalid\"", "out[key] = value",
             ("test_audit_logging.py",), "logging allow-list shapes (T-18)"),
    Mutation("M18-free-form-log-records-pass", "packages/secrets/logging_rules.py",
             "        if not isinstance(fields, dict):\n            with self._lock:\n                self.dropped += 1\n            return False",
             "        if not isinstance(fields, dict):\n            return True",
             ("test_audit_logging.py",), "free-form records on credential logger are dropped (T-18)"),
    Mutation("M19-exception-message-exported", "packages/secrets/telemetry.py",
             "return sanitize_fields(SPAN_EVENT_TYPE, {\"error_class\": type(exc).__name__})",
             "return {\"error_class\": str(exc)}",
             ("test_audit_logging.py",), "exceptions export class name only (T-18)"),
]

# Mutations for later steps are appended by the PR that adds the guarded code.
EXTRA_MUTATIONS: list = []


def run_tests(workdir: Path, modules: tuple) -> tuple:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    failed_any, output = False, []
    for module in modules:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests/security", "-p", module],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=300,
        )
        output.append(proc.stderr)
        if proc.returncode != 0:
            failed_any = True
    return failed_any, "\n".join(output)


def prepare(workdir: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "packages", workdir / "packages", ignore=ignore)
    shutil.copytree(ROOT / "tests" / "security", workdir / "tests" / "security", ignore=ignore)


def main(argv: list) -> int:
    verbose = "-v" in argv
    mutations = MUTATIONS + EXTRA_MUTATIONS
    all_tests = tuple(sorted({t for m in mutations for t in m.tests}))
    with tempfile.TemporaryDirectory(prefix="kan45-mutation-") as tmp:
        base = Path(tmp) / "baseline"
        prepare(base)
        failed, out = run_tests(base, all_tests)
        if failed:
            print("BASELINE FAILS: fix the tests before running mutations")
            print(out[-3000:])
            return 2
        print(f"baseline: tests pass ({len(all_tests)} modules)")
        survivors = 0
        for m in mutations:
            work = Path(tmp) / m.mutation_id
            prepare(work)
            target = work / m.path
            text = target.read_text(encoding="utf-8")
            if text.count(m.old) != 1:
                print(f"{m.mutation_id}: INVALID (pattern found {text.count(m.old)} times, need exactly 1)")
                survivors += 1
                continue
            target.write_text(text.replace(m.old, m.new), encoding="utf-8")
            failed, out = run_tests(work, m.tests)
            status = "KILLED " if failed else "SURVIVED"
            if not failed:
                survivors += 1
            print(f"{m.mutation_id}: {status} ({m.why})")
            if verbose and failed:
                lines = [l for l in out.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
                for l in lines[:4]:
                    print("    " + l)
        print(f"{len(mutations)} mutations, {len(mutations) - survivors} killed, {survivors} survived/invalid")
        return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
