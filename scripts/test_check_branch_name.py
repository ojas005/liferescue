#!/usr/bin/env python3
"""Unit tests for scripts/check-branch-name.py (KAN-20).

Run from the repository root:  python3 -m unittest -v scripts/test_check_branch_name.py
(or: python3 scripts/test_check_branch_name.py)

Cases 1-30 are the table in the KAN-20 implementation plan, section 4.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check-branch-name.py")

_spec = importlib.util.spec_from_file_location("check_branch_name", SCRIPT)
cbn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cbn)

PREFIX_100 = "feature/KAN-20-"
NAME_100 = PREFIX_100 + "a" * (100 - len(PREFIX_100))
NAME_101 = PREFIX_100 + "a" * (101 - len(PREFIX_100))

# (case number, branch name, expected valid, why) - plan section 4
PLAN_CASES = [
    (1, "feature/KAN-20-jira-git-integration", True, "typical"),
    (2, "docs/KAN-50-hosting-event-bus-environments-adr-proposals", True, "future KAN-50 branch"),
    (3, "bugfix/KAN-7-fix-typo", True, "one-digit key"),
    (4, "security/KAN-123-rotate-keys", True, "three-digit key"),
    (5, "chore/KAN-1-bump", True, "minimum shape"),
    (6, "feature/KAN-20-20-more", True, "digits in the description"),
    (7, "feat/KAN-20-x", False, "feat prefix no longer allowed"),
    (8, "hotfix/KAN-20-x", False, "prefix not in the list"),
    (9, "feature/LR-20-x", False, "wrong project key"),
    (10, "feature/KAN-20", False, "no description"),
    (11, "feature/KAN-20-", False, "empty description"),
    (12, "feature/KAN-x-desc", False, "non-numeric key"),
    (13, "feature/KAN-KAN-20-x", False, "placeholder misread"),
    (14, "feature/KAN-020-x", False, "leading zero"),
    (15, "feature/KAN-0-x", False, "key zero"),
    (16, "Feature/KAN-20-x", False, "uppercase prefix"),
    (17, "feature/kan-20-x", False, "lowercase key"),
    (18, "feature/KAN-20-Desc", False, "uppercase in description"),
    (19, "feature/KAN-20-x/y", False, "extra slash"),
    (20, "feature/KAN-20--x", False, "double hyphen"),
    (21, "feature/KAN-20-x-", False, "trailing hyphen"),
    (22, "feature/KAN-20-x_y", False, "underscore"),
    (23, "feature/KAN-20-x y", False, "space"),
    (24, "feature/KAN-20-\u00e9", False, "non-ASCII"),
    (25, "agent/lr04/KAN-20-x", False, "agent prefix not in the list"),
    (26, "main", False, "not a feature branch"),
    (27, "chore/bootstrap-repository-baseline", False, "existing branch, grandfathered"),
    (28, "docs/KAN-orchestration-agent-assignment-registry", False, "no numeric key, grandfathered"),
    (29, NAME_101, False, "101 characters"),
    (30, NAME_100, True, "exactly 100 characters"),
]


def run_cli(args, env_extra=None, drop_env=()):
    """Run the CLI as a child process with an argument list (no shell)."""
    env = {k: v for k, v in os.environ.items() if k not in drop_env}
    env.pop("BRANCH_NAME", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, SCRIPT] + list(args),
        capture_output=True,
        text=True,
        env=env,
        cwd=tempfile.gettempdir(),
    )


class PlanCases(unittest.TestCase):
    def test_length_fixtures(self):
        self.assertEqual(len(NAME_100), 100)
        self.assertEqual(len(NAME_101), 101)

    def test_plan_table_has_30_cases(self):
        self.assertEqual([c[0] for c in PLAN_CASES], list(range(1, 31)))

    def test_all_plan_cases_via_validate(self):
        for number, name, expected_valid, why in PLAN_CASES:
            with self.subTest(case=number, name=name[:60], why=why):
                reason = cbn.validate(name)
                if expected_valid:
                    self.assertIsNone(reason, f"case {number} should be valid")
                else:
                    self.assertIsNotNone(reason, f"case {number} should be invalid")

    def test_all_plan_cases_via_cli_argument(self):
        for number, name, expected_valid, why in PLAN_CASES:
            with self.subTest(case=number, name=name[:60], why=why):
                result = run_cli([name])
                self.assertEqual(result.returncode, 0 if expected_valid else 1, result.stderr)


class HostileAndEdgeInput(unittest.TestCase):
    def test_command_substitution_is_rejected_without_execution(self):
        canary = os.path.join(tempfile.mkdtemp(), "canary")
        for name in (
            "feature/KAN-20-x$(id)",
            f"feature/KAN-20-x$(touch {canary})",
            f"feature/KAN-20-x`touch {canary}`",
            f"feature/KAN-20-x;touch {canary}",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(cbn.validate(name))
                result = run_cli([name])
                self.assertEqual(result.returncode, 1)
                self.assertFalse(os.path.exists(canary), "hostile branch name was executed")
                # the output must not contain the output of `id` (uid=...)
                self.assertNotIn("uid=", result.stdout + result.stderr)

    def test_hostile_name_via_environment_variable(self):
        result = run_cli([], env_extra={"BRANCH_NAME": "feature/KAN-20-x$(id)"})
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("uid=", result.stdout + result.stderr)

    def test_newline_rejected(self):
        for name in ("feature/KAN-20-x\n", "feature/KAN-20-x\nfeature/KAN-20-y", "\nfeature/KAN-20-x"):
            with self.subTest(name=name):
                self.assertIsNotNone(cbn.validate(name))
                self.assertEqual(run_cli([name]).returncode, 1)

    def test_newline_is_escaped_in_output(self):
        result = run_cli(["feature/KAN-20-x\nOK: forged"])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("\nOK: forged", result.stdout + result.stderr)

    def test_backticks_semicolon_and_other_metacharacters_rejected(self):
        for name in (
            "feature/KAN-20-`id`",
            "feature/KAN-20-x;id",
            "feature/KAN-20-x&&id",
            "feature/KAN-20-x|id",
            "feature/KAN-20-x>out",
            "feature/KAN-20-x'y",
            'feature/KAN-20-x"y',
            "feature/KAN-20-x\\y",
            "feature/KAN-20-x\x00y",
            "feature/KAN-20-x\ty",
            "../feature/KAN-20-x",
            "feature/../KAN-20-x",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(cbn.validate(name))

    def test_empty_string_rejected(self):
        self.assertIsNotNone(cbn.validate(""))
        result = run_cli([""])
        self.assertEqual(result.returncode, 1)
        self.assertIn("empty", result.stderr)

    def test_empty_environment_variable_is_invalid_not_missing(self):
        result = run_cli([], env_extra={"BRANCH_NAME": ""})
        self.assertEqual(result.returncode, 1)

    def test_whitespace_only_and_padding_rejected(self):
        for name in (" ", "  feature/KAN-20-x", "feature/KAN-20-x  "):
            with self.subTest(name=name):
                self.assertIsNotNone(cbn.validate(name))

    def test_non_string_rejected(self):
        self.assertIsNotNone(cbn.validate(None))
        self.assertIsNotNone(cbn.validate(b"feature/KAN-20-x"))


class CommandLineInterface(unittest.TestCase):
    def test_valid_via_argument(self):
        result = run_cli(["feature/KAN-20-jira-git-integration"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK", result.stdout)

    def test_valid_via_environment_variable(self):
        result = run_cli([], env_extra={"BRANCH_NAME": "docs/KAN-20-contributing-branch-rules"})
        self.assertEqual(result.returncode, 0)

    def test_custom_environment_variable_name(self):
        result = run_cli(["--env-var", "HEAD_REF"], env_extra={"HEAD_REF": "bugfix/KAN-7-fix-typo"})
        self.assertEqual(result.returncode, 0)

    def test_argument_takes_precedence_over_environment(self):
        result = run_cli(["feat/KAN-20-x"], env_extra={"BRANCH_NAME": "feature/KAN-20-x"})
        self.assertEqual(result.returncode, 1)

    def test_no_input_is_usage_error(self):
        result = run_cli([])
        self.assertEqual(result.returncode, 2)
        self.assertIn("BRANCH_NAME", result.stderr)

    def test_failure_message_lists_allowed_prefixes_and_pattern(self):
        result = run_cli(["feat/KAN-20-x"])
        self.assertEqual(result.returncode, 1)
        for prefix in ("feature", "bugfix", "security", "chore", "docs"):
            self.assertIn(prefix, result.stderr)
        self.assertIn("Allowed prefixes", result.stderr)
        self.assertIn(cbn.PATTERN, result.stderr)

    def test_length_failure_message_mentions_length(self):
        result = run_cli([NAME_101])
        self.assertEqual(result.returncode, 1)
        self.assertIn("101", result.stderr)

    def test_main_function_with_injected_environment(self):
        self.assertEqual(cbn.main([], environ={"BRANCH_NAME": "chore/KAN-1-bump"}), 0)
        self.assertEqual(cbn.main([], environ={}), 2)


class StaticProperties(unittest.TestCase):
    """The validator must stay a pure string check."""

    def test_pattern_is_the_reference_regex(self):
        self.assertEqual(
            cbn.PATTERN,
            r"^(feature|bugfix|security|chore|docs)/KAN-[1-9][0-9]*-[a-z0-9]+(-[a-z0-9]+)*$",
        )
        self.assertEqual(cbn.MAX_LENGTH, 100)
        self.assertEqual(cbn.PREFIXES, ("feature", "bugfix", "security", "chore", "docs"))

    def test_script_has_no_shell_network_or_eval_use(self):
        with open(SCRIPT, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "import subprocess",
            "import socket",
            "import urllib",
            "import http",
            "os.system",
            "os.popen",
            "eval(",
            "exec(",
            "__import__",
        ):
            self.assertNotIn(forbidden, source, forbidden)


if __name__ == "__main__":
    unittest.main()
