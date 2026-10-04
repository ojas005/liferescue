#!/usr/bin/env python3
"""Hostile and edge-case tests for the CI branch-name gate (scripts/ci_branch_gate.py), KAN-20.

Run from the repository root:  python3 -m unittest -v scripts/test_branch_name_ci_cases.py

Every case goes through the real command line (a subprocess with BRANCH_NAME in the environment,
exactly how the workflow calls it) AND in-process. Besides the verdict, each run checks the
output-safety invariants the workflow depends on:
  * the exit code is non-zero for every invalid name (CI treats any non-zero code as failure);
  * the output is plain text with no raw control characters, so the name cannot add output lines;
  * no output line starts with "::" except the single FIXED annotation of the wrapper (the runner only
    acts on workflow commands at the start of a line), so a name such as "::error::x" or
    "x\n::set-output name=a::b" cannot become a workflow command;
  * a canary secret in another environment variable is never printed;
  * a name containing $(...) or backticks does not execute (a canary file is never created).
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "ci_branch_gate.py")

_spec = importlib.util.spec_from_file_location("ci_branch_gate", GATE)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

FIXED_ANNOTATION = (
    "::error title=Branch name::The PR branch name does not follow <type>/KAN-<number>-<description>. "
    "See CONTRIBUTING.md (Branching)."
)
CANARY = "CANARY-SECRET-VALUE-9f3a1c"
BOT = "dependabot[bot]"

# (name, author, expected verdict, label)
VALID = [
    ("feature/KAN-20-x", None, "valid", "minimal feature"),
    ("bugfix/KAN-1-a", None, "valid", "bugfix prefix"),
    ("security/KAN-45-b", None, "valid", "security prefix"),
    ("chore/KAN-20-ci-enforcement", None, "valid", "this PR's own branch"),
    ("chore/KAN-20-ci-valid-probe", None, "valid", "CI probe branch (valid)"),
    ("docs/KAN-5-z", None, "valid", "docs prefix"),
    ("feature/KAN-20-" + "a" * 85, None, "valid", "exactly 100 characters"),
]
EXEMPT = [
    ("chore/bootstrap-repository-baseline", None, "exempt", "legacy exemption (PR #1)"),
    ("docs/KAN-orchestration-agent-assignment-registry", None, "exempt", "legacy exemption (PR #2)"),
    ("dependabot/github_actions/actions/checkout-8", BOT, "exempt", "dependabot by dependabot[bot]"),
    ("dependabot/pip/foo-1.2.3", BOT, "exempt", "dependabot, dots allowed"),
]
HOSTILE = [
    ("zz-test-bad-branch-name", None, "invalid", "throwaway probe name (no prefix)"),
    ("main", None, "invalid", "no prefix"),
    ("", None, "invalid", "empty"),
    (" ", None, "invalid", "space only"),
    ("feature/KAN-20-has space", None, "invalid", "space"),
    ("feature/KAN-20-$(touch CANARYFILE)", None, "invalid", "command substitution"),
    ("feature/KAN-20-`touch CANARYFILE`", None, "invalid", "backticks"),
    ("feature/KAN-20-a;touch CANARYFILE", None, "invalid", "semicolon"),
    ("feature/KAN-20-a|b", None, "invalid", "pipe"),
    ("feature/KAN-20-a&&b", None, "invalid", "and-and"),
    ('feature/KAN-20-a"b', None, "invalid", "double quote"),
    ("feature/KAN-20-a'b", None, "invalid", "single quote"),
    ("feature/KAN-20-a\\b", None, "invalid", "backslash"),
    ("feature/KAN-20-a\nb", None, "invalid", "newline inside"),
    ("feature/KAN-20-x\n", None, "invalid", "trailing newline"),
    ("feature/KAN-20-x\r", None, "invalid", "trailing carriage return"),
    ("feature/KAN-20-x\t", None, "invalid", "trailing tab"),
    ("::error::pwned", None, "invalid", "workflow command as name"),
    ("feature/KAN-20-x\n::error::pwned", None, "invalid", "workflow command on second line"),
    ("feature/KAN-20-x\n::set-output name=a::b", None, "invalid", "set-output injection"),
    ("feature/KAN-20-x\n::add-mask::y", None, "invalid", "add-mask injection"),
    ("feature/KAN-20-x\n::stop-commands::tok", None, "invalid", "stop-commands injection"),
    ("-feature/KAN-20-x", None, "invalid", "leading dash"),
    ("--help", None, "invalid", "option-looking name"),
    ("-", None, "invalid", "single dash"),
    ("feature/../KAN-20-x", None, "invalid", "dot-dot segment"),
    ("feature/KAN-20-..", None, "invalid", "dot-dot suffix"),
    ("../feature/KAN-20-x", None, "invalid", "leading dot-dot"),
    ("refs/heads/feature/KAN-20-x", None, "invalid", "full ref"),
    ("origin/feature/KAN-20-x", None, "invalid", "remote-qualified"),
    ("feature/KAN-20-" + "a" * 86, None, "invalid", "101 characters"),
    ("feature/KAN-20-" + "a" * 5000, None, "invalid", "very long (5000)"),
    ("feature/KAN-20-é", None, "invalid", "unicode letter"),
    ("feature/KAN-20-日本語", None, "invalid", "CJK"),
    ("feature/KAN-２０-x", None, "invalid", "full-width digits"),
    ("feature/KAN-20-\u202ex", None, "invalid", "bidi override"),
    ("feature/KAN-20-x\u200b", None, "invalid", "zero-width space"),
    ("Feature/KAN-20-x", None, "invalid", "capitalised prefix"),
    ("FEATURE/KAN-20-x", None, "invalid", "uppercase prefix"),
    ("feature/kan-20-x", None, "invalid", "lowercase KAN"),
    ("feature-KAN-20-x", None, "invalid", "prefix without slash"),
    ("feature", None, "invalid", "prefix only"),
    ("feature/", None, "invalid", "empty suffix"),
    ("feature/KAN-20-", None, "invalid", "empty description"),
    ("feature/KAN-20", None, "invalid", "no description"),
    ("feature/KAN-0-x", None, "invalid", "key zero"),
    ("feature/KAN-020-x", None, "invalid", "leading zero in key"),
    ("feature/KAN--x", None, "invalid", "no key digits"),
    ("feature/KAN-20-X", None, "invalid", "uppercase description"),
    ("feature/KAN-20--x", None, "invalid", "double hyphen"),
    ("feature/KAN-20-x-", None, "invalid", "trailing hyphen"),
    ("feature//KAN-20-x", None, "invalid", "double slash"),
    ("feature/KAN-20-x/y", None, "invalid", "extra slash"),
    ("feat/KAN-20-x", None, "invalid", "feat is not an allowed prefix"),
    ("hotfix/KAN-20-x", None, "invalid", "hotfix is not an allowed prefix"),
    # exemption near-misses: the exemption is an exact string compare
    ("chore/bootstrap-repository-baseline\n", None, "invalid", "exempt name + newline"),
    ("chore/bootstrap-repository-baseline ", None, "invalid", "exempt name + space"),
    ("chore/bootstrap-repository-baseline-2", None, "invalid", "exempt name + suffix"),
    ("chore/bootstrap-repository-baselin", None, "invalid", "exempt name truncated"),
    ("Chore/bootstrap-repository-baseline", None, "invalid", "exempt name, other case"),
    ("docs/KAN-orchestration-agent-assignment-registry/x", None, "invalid", "exempt name + path"),
    # dependabot exemption is only for dependabot[bot] and safe characters
    ("dependabot/github_actions/x", None, "invalid", "dependabot name, no author"),
    ("dependabot/github_actions/x", "ojas005", "invalid", "dependabot name by a human"),
    ("dependabot/github_actions/x", "dependabot[bot]\n", "invalid", "author with newline"),
    ("dependabot/github_actions/x", "Dependabot[bot]", "invalid", "author other case"),
    ("dependabot/../x", BOT, "invalid", "dependabot with dot-dot segment"),
    ("dependabot/a..b", BOT, "invalid", "dependabot with embedded dot-dot"),
    ("dependabot/a b", BOT, "invalid", "dependabot with space"),
    ("dependabot/$(touch CANARYFILE)", BOT, "invalid", "dependabot with command substitution"),
    ("dependabot/x\n::error::pwned", BOT, "invalid", "dependabot with newline injection"),
    ("dependabot/x\n", BOT, "invalid", "dependabot with trailing newline"),
    ("dependabot/", BOT, "invalid", "dependabot with empty suffix"),
    ("dependabot", BOT, "invalid", "dependabot without slash"),
    ("dependabot//x", BOT, "invalid", "dependabot with double slash"),
    ("Dependabot/x", BOT, "invalid", "dependabot other case"),
    ("dependabot/" + "a" * 300, BOT, "invalid", "dependabot over-long"),
]
ALL = VALID + EXEMPT + HOSTILE


def run_cli(name, author, cwd):
    env = {"PATH": os.environ.get("PATH", ""), "BRANCH_NAME": name, "SECRET_CANARY": CANARY}
    if author is not None:
        env["PR_AUTHOR_LOGIN"] = author
    return subprocess.run(
        [sys.executable, GATE], env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, timeout=30,
    )


class MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_matrix_is_large_and_covers_every_verdict(self):
        verdicts = {v for _, _, v, _ in ALL}
        self.assertEqual(verdicts, {"valid", "exempt", "invalid"})
        self.assertGreaterEqual(len(ALL), 80)

    def test_cli_verdicts_and_output_safety(self):
        validator = gate._load_validator()
        for name, author, verdict, label in ALL:
            with self.subTest(label=label, name=ascii(name)[:80]):
                proc = run_cli(name, author, self.tmp.name)
                out = proc.stdout + proc.stderr
                # exit code: 0 for valid/exempt, exactly 1 for invalid (never 0, never a crash)
                self.assertEqual(proc.returncode, 0 if verdict in ("valid", "exempt") else 1, out)
                # in-process verdict agrees with the CLI
                got, _ = gate.classify(name, author, validator)
                self.assertEqual(got, verdict)
                # plain text, no raw control characters other than "\n" line ends
                self.assertTrue(all(c == "\n" or (c.isprintable() and ord(c) < 0x7F) for c in out), ascii(out))
                # nothing in the output may start a workflow command, except the one FIXED annotation
                for line in out.splitlines():
                    if line.lstrip().startswith("::"):
                        self.assertEqual(line, FIXED_ANNOTATION)
                self.assertEqual(out.count(FIXED_ANNOTATION), 0 if verdict != "invalid" else 1)
                # a name with control characters is never echoed raw (only its escaped form). A "::" in the middle
                # of an escaped line is harmless: the runner acts on a workflow command only at the START of a line.
                if any(not c.isprintable() or ord(c) > 0x7E for c in name):
                    self.assertNotIn(name, out)
                # other environment variables are never printed
                self.assertNotIn(CANARY, out)
                # bounded output: the name is truncated at 120 characters
                self.assertLess(len(out), 3000)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "CANARYFILE")), "a branch name was executed")

    def test_expected_exit_codes_are_never_zero_for_invalid(self):
        for name, author, verdict, label in HOSTILE:
            if verdict == "invalid":
                self.assertNotEqual(run_cli(name, author, self.tmp.name).returncode, 0, label)

    def test_stdout_vs_stderr_of_valid_name(self):
        proc = run_cli("feature/KAN-20-x", None, self.tmp.name)
        self.assertEqual(proc.stdout, "OK: branch name 'feature/KAN-20-x' is valid\n")
        self.assertEqual(proc.stderr, "")

    def test_exempt_output_is_fixed_text(self):
        proc = run_cli("chore/bootstrap-repository-baseline", None, self.tmp.name)
        self.assertEqual(proc.stdout, "EXEMPT: legacy: bootstrap baseline branch (PR #1, merged)\n")

    def test_unset_branch_name_is_usage_error(self):
        proc = subprocess.run([sys.executable, GATE], env={"PATH": os.environ.get("PATH", "")}, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, cwd=self.tmp.name)
        self.assertEqual(proc.returncode, 2)

    def test_arguments_are_refused_and_not_echoed(self):
        for args in (["-h"], ["--help"], ["--"], ["feature/KAN-20-x"], ["$(id)"], [""]):
            proc = subprocess.run([sys.executable, GATE] + args, env={"PATH": os.environ.get("PATH", ""), "BRANCH_NAME": "feature/KAN-20-x"},
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, cwd=self.tmp.name)
            self.assertEqual(proc.returncode, 2, args)
            self.assertNotIn(args[0] or "\0", proc.stdout + proc.stderr)

    def test_nul_byte_and_non_str_in_process(self):
        validator = gate._load_validator()
        for bad in ("feature/KAN-20-x\x00", "feature/KAN-20-x\x00::error::y", None, b"feature/KAN-20-x", 5):
            self.assertEqual(gate.classify(bad, None, validator)[0], "invalid", repr(bad))

    def test_shell_metacharacters_do_not_run_when_passed_through_env(self):
        # the workflow equivalent: env var -> `run: python3 scripts/ci_branch_gate.py` (no interpolation)
        env = {"PATH": os.environ.get("PATH", ""), "BRANCH_NAME": "feature/KAN-20-$(touch CANARYFILE2);`touch CANARYFILE2`"}
        subprocess.run(["bash", "-c", '"%s" "%s"' % (sys.executable, GATE)], env=env, cwd=self.tmp.name,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "CANARYFILE2")))

    def test_exemption_list_is_exactly_the_documented_set(self):
        self.assertEqual(
            set(gate.EXACT_EXEMPTIONS),
            {"chore/bootstrap-repository-baseline", "docs/KAN-orchestration-agent-assignment-registry"},
        )
        validator = gate._load_validator()
        # every exemption entry really is a name the rule rejects (otherwise the entry is dead weight)
        for name in gate.EXACT_EXEMPTIONS:
            self.assertIsNotNone(validator.validate(name), name)


if __name__ == "__main__":
    unittest.main()
