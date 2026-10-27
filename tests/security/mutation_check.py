#!/usr/bin/env python3
"""Mutation check for the KAN-45 secret-management tests (spec T-24 spirit: test the tests).

For each mutation: copy ``packages/`` and ``tests/security/`` to a temp dir, remove or break ONE
guard with an exact text replacement, run the named test modules there, and require that they FAIL.
A mutation that survives (tests still pass) means a guard is not really tested; the script exits 1.
The working tree is never modified. Standard library only.

Usage (from the repository root):   python3 tests/security/mutation_check.py [-v] [--gitleaks-config PATH]
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
    needs_gitleaks: bool = False  # only killable when a real .gitleaks.toml is supplied (--gitleaks-config)


MUTATIONS = [
    Mutation(
        "M01-production-check-removed",
        "packages/secrets/broker.py",
        "if req.ref.environment is Environment.PRODUCTION:",
        "if False:",
        ("test_broker.py",),
        "constant PRODUCTION refusal (T-14, I-5)",
    ),
    Mutation(
        "M02-config-allows-production",
        "packages/secrets/config.py",
        "if Environment.PRODUCTION in envs:",
        "if False:",
        ("test_config_backend.py",),
        "config must reject PRODUCTION (T-14)",
    ),
    Mutation(
        "M03-policy-accepts-production-grant",
        "packages/secrets/policy.py",
        "if env is Environment.PRODUCTION:",
        "if False:",
        ("test_policy.py", "test_broker.py"),
        "policy must reject a PRODUCTION grant (T-14)",
    ),
    Mutation(
        "M04-lease-never-expires",
        "packages/secrets/broker.py",
        "or mono < lease.expires_mono:",
        "or True:",
        ("test_broker.py", "test_audit_logging.py"),
        "TTL expiry (T-06)",
    ),
    Mutation(
        "M05-secretvalue-str-leaks",
        "packages/secrets/secret_types.py",
        "    def __str__(self) -> str:\n        return REDACTED",
        "    def __str__(self) -> str:\n        return self._decode()",
        ("test_secret_types.py", "test_broker.py"),
        "SecretValue must not print (T-02, I-1)",
    ),
    Mutation(
        "M06-secretvalue-pickle-allowed",
        "packages/secrets/secret_types.py",
        '    def __reduce_ex__(self, protocol):\n        raise TypeError("SecretValue cannot be pickled")',
        "    def __reduce_ex__(self, protocol):\n        return (SecretValue, (self._decode(),))",
        ("test_secret_types.py",),
        "SecretValue must not pickle (T-02)",
    ),
    Mutation(
        "M07-context-check-removed",
        "packages/secrets/broker.py",
        "if (context.task_id, context.run_id, context.agent_id) != (lease.task_id, lease.run_id, lease.agent_id):",
        "if False:",
        ("test_broker.py",),
        "handle bound to task/run/agent (T-08, I-3)",
    ),
    Mutation(
        "M08-gateway-identity-not-checked",
        "packages/secrets/broker.py",
        "return hmac.compare_digest(expected.encode(), caller._token.encode())",
        "return True",
        ("test_broker.py",),
        "only registered gateways may use (T-09)",
    ),
    Mutation(
        "M09-revoke-task-noop",
        "packages/secrets/broker.py",
        "for lease in [l for l in self._leases.values() if l.task_id == task_id]:",
        "for lease in [l for l in self._leases.values() if False]:",
        ("test_broker.py", "test_audit_logging.py"),
        "task end revokes all leases (T-07, I-4)",
    ),
    Mutation(
        "M10-deny-by-default-removed",
        "packages/secrets/policy.py",
        "and ref.name in grant.names",
        "and True",
        ("test_policy.py", "test_broker.py"),
        "deny by default for unlisted names (T-03, T-04)",
    ),
    Mutation(
        "M11-duplicate-lease-allowed",
        "packages/secrets/broker.py",
        "if any(l.ref == req.ref for l in live):",
        "if False:",
        ("test_broker.py",),
        "one lease per (task, ref) (T-11)",
    ),
    Mutation(
        "M12-ttl-ceiling-removed",
        "packages/secrets/broker.py",
        "if ttl > ceiling:",
        "if False:",
        ("test_broker.py",),
        "TTL above maximum is denied (T-05)",
    ),
    Mutation(
        "M13-task-liveness-not-checked",
        "packages/secrets/broker.py",
        "        if not live:\n            raise _Refuse(DenialReason.TASK_NOT_LIVE)",
        "        if False:\n            raise _Refuse(DenialReason.TASK_NOT_LIVE)",
        ("test_broker.py",),
        "task must be live (spec 4.3 rule 4)",
    ),
    Mutation(
        "M14-clock-regression-ignored",
        "packages/secrets/broker.py",
        "elif self._last_mono is not None and mono < self._last_mono:",
        "elif False:",
        ("test_broker.py",),
        "clock fault fails closed (T-13, T-29)",
    ),
    Mutation(
        "M15-backend-health-ignored",
        "packages/secrets/broker.py",
        "if not self._backend_healthy():",
        "if False:",
        ("test_broker.py",),
        "backend down fails closed (T-13)",
    ),
    Mutation(
        "M16-audit-field-sanitising-removed",
        "packages/secrets/audit.py",
        '    return "invalid"',
        "    return value",
        ("test_audit_logging.py",),
        "audit fields are shape-checked (I-6)",
    ),
    Mutation(
        "M17-log-field-shape-check-removed",
        "packages/secrets/logging_rules.py",
        "if not FIELD_SHAPES[key](value):",
        "if False:",
        ("test_audit_logging.py",),
        "logging allow-list shapes (T-18)",
    ),
    Mutation(
        "M18-free-form-log-records-pass",
        "packages/secrets/logging_rules.py",
        "        if not isinstance(fields, dict):\n            with self._lock:\n                self.dropped += 1\n            return False",
        "        if not isinstance(fields, dict):\n            return True",
        ("test_audit_logging.py",),
        "free-form records on credential logger are dropped (T-18)",
    ),
    Mutation(
        "M19-exception-message-exported",
        "packages/secrets/telemetry.py",
        'return sanitize_fields(SPAN_EVENT_TYPE, {"error_class": type(exc).__name__})',
        'return {"error_class": str(exc)}',
        ("test_audit_logging.py",),
        "exceptions export class name only (T-18)",
    ),
]

# Mutations for the redaction / guards / parity / conformance code (second PR, spec steps 5 to 7).
EXTRA_MUTATIONS: list = [
    Mutation(
        "P01-known-value-redaction-removed",
        "packages/secrets/redaction.py",
        "return _merge(self._current_matcher().spans(text) + self._patterns.spans(text))",
        "return _merge(self._patterns.spans(text))",
        ("test_redaction.py", "test_guards.py", "test_e2e_sweep.py"),
        "known-value redaction (T-16, T-19, T-23)",
    ),
    Mutation(
        "P02-base64-variants-removed",
        "packages/secrets/redaction.py",
        "forms |= base64_variants(data)",
        "pass",
        ("test_redaction.py",),
        "base64 forms of a leased value (T-16)",
    ),
    Mutation(
        "P03-split-form-detection-removed",
        "packages/secrets/redaction.py",
        "    if len(value) < MIN_VARIANT_LEN or len(value) > MAX_SPLIT_LEN:\n        return None",
        "    return None",
        ("test_redaction.py", "test_guards.py"),
        "value split across lines (T-16)",
    ),
    Mutation(
        "P04-key-name-rule-disabled",
        "packages/secrets/redaction.py",
        "return any(term in norm for term in DENIED_KEY_TERMS)",
        "return False",
        ("test_redaction.py", "test_guards.py"),
        "key-name rule (T-17)",
    ),
    Mutation(
        "P05-pattern-redaction-disabled",
        "packages/secrets/redaction.py",
        "out.append((start, end, rule.kind))",
        "pass",
        (
            "test_redaction.py",
            "test_guards.py",
            "test_e2e_sweep.py",
            "test_repo_scan.py",
        ),
        "key-shaped string redaction",
    ),
    Mutation(
        "P06-prompt-guard-does-not-refuse",
        "packages/secrets/broker.py",
        "raise SecretLeak(sink_name, kinds)",
        "return",
        ("test_guards.py", "test_e2e_sweep.py"),
        "prompt guard fails closed (T-19)",
    ),
    Mutation(
        "P07-persistence-guard-bypassed",
        "packages/secrets/guards.py",
        'self._broker.assert_safe_to_emit_obj(record, sink="persistence")',
        "pass",
        ("test_guards.py", "test_e2e_sweep.py"),
        "persistence guard (T-20)",
    ),
    Mutation(
        "P08-return-path-not-redacted",
        "packages/secrets/guards.py",
        'return self._redactor.redact(response, sink="return")',
        "return response",
        ("test_guards.py", "test_e2e_sweep.py"),
        "return path to agent is redacted (T-21)",
    ),
    Mutation(
        "P09-provider-error-not-redacted",
        "packages/secrets/guards.py",
        '"error": self._redactor.redact_exception(exc, sink="return")',
        '"error": str(exc)',
        ("test_guards.py", "test_e2e_sweep.py"),
        "provider error body reaches agent redacted (T-21)",
    ),
    Mutation(
        "P10-retry-of-blocked-prompt-allowed",
        "packages/secrets/guards.py",
        "if digest in self._blocked:",
        "if False:",
        ("test_guards.py",),
        "no retry with the same blocked text (T-19)",
    ),
    Mutation(
        "P11-audit-writer-scrub-removed",
        "packages/secrets/guards.py",
        "if isinstance(value, str) and self._r.contains_secret(value):",
        "if False:",
        ("test_guards.py",),
        "audit sink never stores a leased value (T-18, T-30)",
    ),
    Mutation(
        "P12-log-message-not-redacted",
        "packages/secrets/guards.py",
        'record.msg = self._r.redact_text(message, sink="log")',
        "record.msg = message",
        ("test_guards.py", "test_e2e_sweep.py"),
        "log lines are redacted (T-16)",
    ),
    Mutation(
        "P13-exception-text-not-redacted",
        "packages/secrets/redaction.py",
        "return self.redact_text(self.redact_exception_raw_text(exc), sink=sink)",
        "return self.redact_exception_raw_text(exc)",
        ("test_redaction.py", "test_guards.py", "test_e2e_sweep.py"),
        "exceptions and chained causes are redacted (spec 6.7)",
    ),
    Mutation(
        "P14-outgoing-guard-bypassed",
        "packages/secrets/guards.py",
        'self._broker.assert_safe_to_emit_obj(text, sink="outgoing")',
        "pass",
        ("test_guards.py", "test_e2e_sweep.py"),
        "PR/Jira/chat text helper refuses secrets",
    ),
    Mutation(
        "P15-telemetry-known-value-check-ignored",
        "packages/secrets/logging_rules.py",
        "elif leak_check is not None and isinstance(value, str) and leak_check(value):",
        "elif False:",
        ("test_guards.py",),
        "telemetry/log allowed fields scrubbed of leased values (T-18)",
    ),
    Mutation(
        "P16-mock-backend-accepts-zero-ttl",
        "packages/secrets/memory_backend.py",
        "if not isinstance(ttl, timedelta) or ttl <= timedelta(0):",
        "if not isinstance(ttl, timedelta):",
        ("test_backend_conformance.py", "test_config_backend.py"),
        "conformance suite catches a TTL-less backend (T-27)",
    ),
    Mutation(
        "P17-parity-harness-ignores-mismatches",
        "packages/secrets/parity.py",
        "if (g is None) != (p is None):",
        'if (g is None) != (p is None) and kind == "positive":',
        ("test_pattern_parity.py",),
        "parity harness can fail (T-22)",
    ),
    Mutation(
        "P18-redactor-xai-pattern-drifts-from-scanner",
        "packages/secrets/patterns.json",
        "\\\\bxai-[A-Za-z0-9]{40,}\\\\b",
        "\\\\bxai-[A-Za-z0-9]{30,}\\\\b",
        ("test_pattern_parity.py",),
        "pattern drift vs .gitleaks.toml (T-22)",
        True,
    ),
]


def run_tests(workdir: Path, modules: tuple, extra_env: dict = None) -> tuple:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **(extra_env or {}))
    failed_any, output = False, []
    for module in modules:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests/security",
                "-p",
                module,
            ],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output.append(proc.stderr)
        if proc.returncode != 0:
            failed_any = True
    return failed_any, "\n".join(output)


def prepare(workdir: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "packages", workdir / "packages", ignore=ignore)
    shutil.copytree(
        ROOT / "tests" / "security", workdir / "tests" / "security", ignore=ignore
    )


def main(argv: list) -> int:
    verbose = "-v" in argv
    gitleaks_config = None
    if "--gitleaks-config" in argv:
        gitleaks_config = argv[argv.index("--gitleaks-config") + 1]
    extra_env = {"KAN45_GITLEAKS_CONFIG": gitleaks_config} if gitleaks_config else {}
    mutations = MUTATIONS + EXTRA_MUTATIONS
    all_tests = tuple(sorted({t for m in mutations for t in m.tests}))
    with tempfile.TemporaryDirectory(prefix="kan45-mutation-") as tmp:
        base = Path(tmp) / "baseline"
        prepare(base)
        failed, out = run_tests(base, all_tests, extra_env)
        if failed:
            print("BASELINE FAILS: fix the tests before running mutations")
            print(out[-3000:])
            return 2
        print(f"baseline: tests pass ({len(all_tests)} modules)")
        survivors = 0
        skipped = 0
        for m in mutations:
            if m.needs_gitleaks and not gitleaks_config:
                print(
                    f"{m.mutation_id}: NOT RUN (needs --gitleaks-config PATH; the real-config parity test is skipped otherwise) ({m.why})"
                )
                skipped += 1
                continue
            work = Path(tmp) / m.mutation_id
            prepare(work)
            target = work / m.path
            text = target.read_text(encoding="utf-8")
            if text.count(m.old) != 1:
                print(
                    f"{m.mutation_id}: INVALID (pattern found {text.count(m.old)} times, need exactly 1)"
                )
                survivors += 1
                continue
            target.write_text(text.replace(m.old, m.new), encoding="utf-8")
            failed, out = run_tests(work, m.tests, extra_env)
            status = "KILLED " if failed else "SURVIVED"
            if not failed:
                survivors += 1
            print(f"{m.mutation_id}: {status} ({m.why})")
            if verbose and failed:
                lines = [
                    line
                    for line in out.splitlines()
                    if line.startswith(("FAIL:", "ERROR:"))
                ]
                for line in lines[:4]:
                    print("    " + line)
        print(
            f"{len(mutations)} mutations, {len(mutations) - survivors - skipped} killed, {survivors} survived/invalid, {skipped} not run"
        )
        return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
