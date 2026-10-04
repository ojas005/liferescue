#!/usr/bin/env python3
"""Unit tests for scripts/check-branch-name.py (KAN-20).

Run from the repository root:  python3 -m unittest -v scripts/test_check_branch_name.py
(or: python3 scripts/test_check_branch_name.py)

Cases 1-30 are the table in the KAN-20 implementation plan, section 4.
"""
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import types
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
    """Run the CLI as a child process with an argument list (no shell).

    The script accepts no arguments (F-1/F-2); `args` is only non-empty in the tests that prove
    that arguments are refused. The branch name goes in the environment variable BRANCH_NAME.
    """
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


def run_name(name):
    """Run the CLI with the branch name in BRANCH_NAME (the only supported interface)."""
    return run_cli([], env_extra={"BRANCH_NAME": name})


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

    def test_all_plan_cases_via_cli_environment_variable(self):
        for number, name, expected_valid, why in PLAN_CASES:
            with self.subTest(case=number, name=name[:60], why=why):
                result = run_name(name)
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
                result = run_name(name)
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
                self.assertEqual(run_name(name).returncode, 1)

    def test_newline_is_escaped_in_output(self):
        result = run_name("feature/KAN-20-x\nOK: forged")
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
        result = run_name("")
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
    def test_valid_via_environment_variable(self):
        result = run_cli([], env_extra={"BRANCH_NAME": "docs/KAN-20-contributing-branch-rules"})
        self.assertEqual(result.returncode, 0)

    def test_no_input_is_usage_error(self):
        result = run_cli([])
        self.assertEqual(result.returncode, 2)
        self.assertIn("BRANCH_NAME", result.stderr)

    def test_failure_message_lists_allowed_prefixes_and_pattern(self):
        result = run_name("feat/KAN-20-x")
        self.assertEqual(result.returncode, 1)
        for prefix in ("feature", "bugfix", "security", "chore", "docs"):
            self.assertIn(prefix, result.stderr)
        self.assertIn("Allowed prefixes", result.stderr)
        self.assertIn(cbn.PATTERN, result.stderr)

    def test_length_failure_message_mentions_length(self):
        result = run_name(NAME_101)
        self.assertEqual(result.returncode, 1)
        self.assertIn("101", result.stderr)

    def test_main_function_with_injected_environment(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cbn.main([], environ={"BRANCH_NAME": "chore/KAN-1-bump"}), 0)
            self.assertEqual(cbn.main([], environ={}), 2)
            self.assertEqual(cbn.main(["chore/KAN-1-bump"], environ={"BRANCH_NAME": "chore/KAN-1-bump"}), 2)


SYNTHETIC_VAR = "KAN20_SYNTHETIC_SECRET"
SYNTHETIC_VALUE = "synthetic-secret-value-0123456789"
USAGE_ERROR = "error: this script takes no arguments; set the environment variable BRANCH_NAME\n"

# Everything a caller (or a hostile branch name passed on a command line) might use to steer the
# old argparse interface (F-1) or to get help text and exit 0 (F-2).
REFUSED_ARGV = [
    ["--env-var=" + SYNTHETIC_VAR],
    ["--env-var", SYNTHETIC_VAR],
    ["--env=" + SYNTHETIC_VAR],
    ["--e=" + SYNTHETIC_VAR],
    ["--env-var=PATH"],
    ["--env-var", "PATH"],
    ["--env-var=BRANCH_NAME"],
    ["-h"],
    ["--help"],
    ["--hel"],
    ["--"],
    ["--", "feature/KAN-20-x"],
    ["-"],
    [""],
    ["feature/KAN-20-x"],
    ["feat/KAN-20-x"],
    ["feature/KAN-20-x", "feature/KAN-20-y"],
    ["--version"],
    ["$(id)"],
]


class ArgumentsAreRefused(unittest.TestCase):
    """F-1 (argv injection through --env-var) and F-2 (-h / --help failed open with exit 0)."""

    def run_with_secret(self, args, branch_name=None):
        env_extra = {SYNTHETIC_VAR: SYNTHETIC_VALUE}
        if branch_name is not None:
            env_extra["BRANCH_NAME"] = branch_name
        return run_cli(args, env_extra=env_extra)

    def test_any_argument_is_a_usage_error_with_or_without_a_valid_environment_name(self):
        for args in REFUSED_ARGV:
            for branch_name in (None, "feature/KAN-20-x", "not-a-branch"):
                with self.subTest(args=args, branch_name=branch_name):
                    result = self.run_with_secret(args, branch_name)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertNotEqual(result.returncode, 0)

    def test_arguments_never_echo_environment_values_or_the_argument_itself(self):
        path_value = os.environ.get("PATH", "")
        self.assertTrue(path_value)
        for args in REFUSED_ARGV:
            with self.subTest(args=args):
                result = self.run_with_secret(args, "feature/KAN-20-x")
                output = result.stdout + result.stderr
                self.assertNotIn(SYNTHETIC_VALUE, output)
                self.assertNotIn(path_value, output)
                self.assertEqual(result.stdout, "")
                # one fixed message, identical for every argument list: nothing from argv is printed
                self.assertEqual(result.stderr, USAGE_ERROR)

    def test_help_text_is_never_printed(self):
        for args in (["-h"], ["--help"], ["--hel"], ["--he"]):
            with self.subTest(args=args):
                result = run_cli(args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("usage:", result.stdout + result.stderr.lower().replace("error:", ""))
                self.assertNotIn("options:", (result.stdout + result.stderr).lower())

    def test_dash_names_in_the_environment_variable_are_invalid_not_options(self):
        for name in ("-h", "--help", "--", "--env-var=" + SYNTHETIC_VAR, "--env-var=PATH", "-x", "--version"):
            with self.subTest(name=name):
                result = self.run_with_secret([], name)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn(SYNTHETIC_VALUE, result.stdout + result.stderr)
                self.assertNotIn(os.environ.get("PATH", "<none>"), result.stdout + result.stderr)
                # the (escaped) name itself is echoed once as data, not interpreted
                self.assertIn(ascii(name), result.stderr)

    def test_only_the_fixed_variable_is_read(self):
        for other in ("HEAD_REF", "GITHUB_HEAD_REF", "BRANCH", "branch_name", SYNTHETIC_VAR):
            with self.subTest(other=other):
                result = run_cli([], env_extra={other: "feature/KAN-20-x"})
                self.assertEqual(result.returncode, 2)
                self.assertIn("BRANCH_NAME", result.stderr)

    def test_main_function_refuses_arguments_in_process(self):
        environ = {"BRANCH_NAME": "feature/KAN-20-x", SYNTHETIC_VAR: SYNTHETIC_VALUE}
        for args in REFUSED_ARGV:
            with self.subTest(args=args):
                buffer = io.StringIO()
                with contextlib.redirect_stderr(buffer), contextlib.redirect_stdout(buffer):
                    code = cbn.main(args, environ=dict(environ))
                self.assertEqual(code, 2)
                self.assertNotIn(SYNTHETIC_VALUE, buffer.getvalue())

    def test_canary_hostile_arguments_and_names_never_execute(self):
        canary = os.path.join(tempfile.mkdtemp(), "canary")
        payloads = [f"$(touch {canary})", f"`touch {canary}`", f";touch {canary}", f"--env-var=$(touch {canary})",
                    f"feature/KAN-20-x$(touch {canary})"]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(run_cli([payload]).returncode, 2)
                self.assertEqual(run_name(payload).returncode, 1)
                self.assertFalse(os.path.exists(canary), "hostile input was executed")


class OutputIsBounded(unittest.TestCase):
    """F-3: a very long name is echoed only up to ECHO_LIMIT characters (still escaped with ascii())."""

    def test_echo_limit_constant(self):
        self.assertEqual(cbn.ECHO_LIMIT, 120)

    def test_very_long_ascii_name(self):
        result = run_name("feature/KAN-20-" + "a" * 100000)
        self.assertEqual(result.returncode, 1)
        self.assertLess(len(result.stderr), 1500)
        self.assertIn("truncated", result.stderr)
        self.assertIn("100015", result.stderr)  # total length is still reported

    def test_long_name_of_characters_that_expand_when_escaped(self):
        result = run_name("\U0010ffff" * 5000)
        self.assertEqual(result.returncode, 1)
        self.assertLess(len(result.stderr), 3000)  # 120 chars x at most 10 escaped characters each + messages
        self.assertTrue(result.stderr.isascii())

    def test_escaped_helper(self):
        self.assertEqual(cbn.escaped("abc"), "'abc'")
        self.assertEqual(cbn.escaped("a\nb"), "'a\\nb'")
        self.assertEqual(cbn.escaped("a" * 120), ascii("a" * 120))
        long = cbn.escaped("a" * 121)
        self.assertTrue(long.startswith(ascii("a" * 120)))
        self.assertIn("truncated; 121 characters", long)
        self.assertLess(len(cbn.escaped("x" * 10 ** 6)), 200)

    def test_output_is_ascii_single_line_for_hostile_names(self):
        for name in ("feature/KAN-20-x\r\nOK: forged", "\x1b[31mred", "\u202eevil", "é" * 500):
            with self.subTest(name=name[:20]):
                result = run_name(name)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(result.stderr.isascii())
                self.assertNotIn("\nOK:", result.stderr)

    def test_valid_name_is_still_echoed_fully(self):
        result = run_name(NAME_100)
        self.assertEqual(result.returncode, 0)
        self.assertIn(NAME_100, result.stdout)


class ExitCodes(unittest.TestCase):
    def test_exit_codes(self):
        self.assertEqual(run_name("feature/KAN-20-x").returncode, 0)
        self.assertEqual(run_name("feat/KAN-20-x").returncode, 1)
        self.assertEqual(run_name("").returncode, 1)  # empty is invalid, not "missing"
        self.assertEqual(run_cli([]).returncode, 2)  # not set
        self.assertEqual(run_cli(["feature/KAN-20-x"]).returncode, 2)  # argument


# ---------------------------------------------------------------------------------------------
# mutation check: the guard tests must FAIL when the guard is removed from the script
# ---------------------------------------------------------------------------------------------

ARGV_GUARD = "    if argv:\n"
ECHO_GUARD = "    if len(name) > ECHO_LIMIT:\n"


def load_mutant(replacements):
    """Load a copy of check-branch-name.py with exact-text replacements (each must match once)."""
    with open(SCRIPT, encoding="utf-8") as fh:
        source = fh.read()
    for old, new in replacements:
        if source.count(old) != 1:
            raise AssertionError(f"mutation target not found exactly once: {old!r}")
        source = source.replace(old, new)
    module = types.ModuleType("check_branch_name_mutant")
    module.__file__ = SCRIPT
    exec(compile(source, SCRIPT, "exec"), module.__dict__)
    return module


def assert_argv_is_refused(test, module):
    """Guard test for F-1/F-2: arguments (even a valid-looking name) must give exit 2, never print env values."""
    environ = {"BRANCH_NAME": "feature/KAN-20-x", SYNTHETIC_VAR: SYNTHETIC_VALUE}
    for args in (["--env-var=" + SYNTHETIC_VAR], ["-h"], ["--help"], ["feature/KAN-20-x"]):
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer), contextlib.redirect_stdout(buffer):
            code = module.main(args, environ=dict(environ))
        test.assertEqual(code, 2, args)


def assert_echo_is_bounded(test, module):
    test.assertLess(len(module.escaped("x" * 10 ** 6)), 200)


class MutationChecks(unittest.TestCase):
    def test_unmutated_script_passes_the_guard_tests(self):
        assert_argv_is_refused(self, cbn)
        assert_echo_is_bounded(self, cbn)

    def test_removing_the_argument_guard_makes_its_test_fail(self):
        mutant = load_mutant([(ARGV_GUARD, "    if False:\n")])
        with self.assertRaises(AssertionError):
            assert_argv_is_refused(self, mutant)

    def test_removing_the_echo_bound_makes_its_test_fail(self):
        mutant = load_mutant([(ECHO_GUARD, "    if False:\n")])
        with self.assertRaises(AssertionError):
            assert_echo_is_bounded(self, mutant)

    def test_mutation_harness_rejects_a_stale_target(self):
        with self.assertRaises(AssertionError):
            load_mutant([("this text is not in the script", "x")])


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
            # F-1/F-2: no option parsing and no configurable variable name
            "argparse",
            "--env-var",
            "add_argument",
            "getopt",
            "optparse",
        ):
            self.assertNotIn(forbidden, source, forbidden)


if __name__ == "__main__":
    unittest.main()
