#!/usr/bin/env python3
"""Unit tests for scripts/ci_gate.py (ci-gate decision logic) and scripts/ci_jira_status_dryrun.py (DRY-RUN stub), KAN-20.

Run from the repository root:  python3 -m unittest -v scripts/test_ci_helpers.py
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci_gate = load("ci_gate", "ci_gate.py")
dryrun = load("ci_jira_status_dryrun", "ci_jira_status_dryrun.py")


def needs(contract=False, overrides=None, detect_result="success"):
    """A `needs` object as the runner would provide it for a run with no failures."""
    n = {
        "secret-scan": {"result": "success", "outputs": {}},
        "repo-validation": {"result": "success", "outputs": {}},
        "detect": {"result": detect_result, "outputs": {"contract": str(contract).lower()}},
        "python-unit-tests": {"result": "success", "outputs": {}},
        "security-corpus": {"result": "success", "outputs": {}},
        "dependency-audit": {"result": "success", "outputs": {}},
        "branch-name": {"result": "success", "outputs": {}},
        "pr-link-check": {"result": "success", "outputs": {}},
        "contract-tests": {"result": "success" if contract else "skipped", "outputs": {}},
        "arch-check": {"result": "success" if contract else "skipped", "outputs": {}},
    }
    for k, v in (overrides or {}).items():
        if v is None:
            del n[k]
        else:
            n[k] = {"result": v, "outputs": n.get(k, {}).get("outputs", {})}
    return n


def push_needs(**kw):
    return needs(overrides=dict({"branch-name": "skipped", "pr-link-check": "skipped"}, **kw.pop("overrides", {})), **kw)


class GateTests(unittest.TestCase):
    def ok(self, n, event="pull_request"):
        return ci_gate.evaluate(n, event)[0]

    def test_pull_request_all_good(self):
        self.assertTrue(self.ok(needs()))

    def test_push_with_pr_only_jobs_skipped(self):
        self.assertTrue(self.ok(push_needs(), "push"))

    def test_per_package_jobs_active_and_successful(self):
        self.assertTrue(self.ok(needs(contract=True)))
        self.assertTrue(self.ok(push_needs(contract=True), "push"))

    def test_every_blocking_job_failing_fails_the_gate(self):
        for job in list(needs()):
            if job in ci_gate.REPORT_ONLY:
                continue
            for bad in ("failure", "cancelled", "skipped"):
                if needs()[job]["result"] == bad:
                    continue  # that is the legitimate value
                with self.subTest(job=job, bad=bad):
                    self.assertFalse(self.ok(needs(overrides={job: bad})))

    def test_every_blocking_job_failing_fails_the_gate_when_packages_are_present(self):
        for job in list(needs(contract=True)):
            if job in ci_gate.REPORT_ONLY:
                continue
            for bad in ("failure", "cancelled", "skipped"):
                if needs(contract=True)[job]["result"] == bad:
                    continue
                with self.subTest(job=job, bad=bad):
                    self.assertFalse(self.ok(needs(contract=True, overrides={job: bad})))

    def test_skipped_required_job_is_not_a_pass(self):
        for job in ("secret-scan", "repo-validation", "detect", "python-unit-tests", "security-corpus", "branch-name", "pr-link-check"):
            self.assertFalse(self.ok(needs(overrides={job: "skipped"})), job)

    def test_pr_only_job_must_be_skipped_on_push(self):
        self.assertFalse(self.ok(needs(), "push"))
        self.assertFalse(self.ok(push_needs(overrides={"branch-name": "success"}), "push"))

    def test_per_package_job_that_should_run_but_is_skipped_fails(self):
        for job in ("contract-tests", "arch-check"):
            self.assertFalse(self.ok(needs(contract=True, overrides={job: "skipped"})), job)

    def test_per_package_job_failure_fails(self):
        for job in ("contract-tests", "arch-check"):
            for bad in ("failure", "cancelled"):
                self.assertFalse(self.ok(needs(contract=True, overrides={job: bad})), (job, bad))

    def test_per_package_job_ran_although_detect_said_no_fails(self):
        for job in ("contract-tests", "arch-check"):
            self.assertFalse(self.ok(needs(overrides={job: "success"})), job)

    def test_missing_per_package_job_fails_closed(self):
        for contract in (False, True):
            for job in ("contract-tests", "arch-check"):
                self.assertFalse(self.ok(needs(contract=contract, overrides={job: None})), (contract, job))

    def test_report_only_audit_never_blocks_but_must_be_present(self):
        for res in ("success", "failure", "cancelled", "skipped"):
            self.assertTrue(self.ok(needs(overrides={"dependency-audit": res})), res)
            self.assertTrue(self.ok(needs(contract=True, overrides={"dependency-audit": res})), res)
        self.assertFalse(self.ok(needs(overrides={"dependency-audit": None})))
        n = needs()
        n["dependency-audit"] = "success"  # not an object
        self.assertFalse(self.ok(n))
        n = needs()
        n["dependency-audit"]["result"] = "weird"
        self.assertFalse(self.ok(n))

    def test_old_root_level_job_ids_are_unknown_to_the_gate(self):
        # the dormant root jobs are gone; listing one in `needs` must not be accepted silently
        for job in ("node-checks", "python-checks", "dependency-scan", "sbom"):
            n = needs()
            n[job] = {"result": "skipped", "outputs": {}}
            self.assertFalse(self.ok(n), job)

    def test_detect_not_successful_or_odd_outputs_fail(self):
        self.assertFalse(self.ok(needs(detect_result="failure")))
        n = needs()
        n["detect"]["outputs"]["contract"] = ""
        self.assertFalse(self.ok(n))
        n = needs()
        del n["detect"]["outputs"]
        self.assertFalse(self.ok(n))
        n = needs()
        del n["detect"]["outputs"]["contract"]
        self.assertFalse(self.ok(n))

    def test_missing_job_and_unknown_job_fail(self):
        self.assertFalse(self.ok(needs(overrides={"secret-scan": None})))
        self.assertFalse(self.ok(needs(overrides={"security-corpus": None})))
        n = needs()
        n["brand-new-job"] = {"result": "success", "outputs": {}}
        self.assertFalse(self.ok(n))

    def test_unexpected_result_words_fail(self):
        self.assertFalse(self.ok(needs(overrides={"secret-scan": "weird"})))
        n = needs()
        n["secret-scan"] = "success"
        self.assertFalse(self.ok(n))

    def run_cli(self, env):
        full = {"PATH": os.environ.get("PATH", "")}
        full.update(env)
        return subprocess.run([sys.executable, os.path.join(HERE, "ci_gate.py")], env=full, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True)

    def test_cli_exit_codes(self):
        good = self.run_cli({"NEEDS_JSON": json.dumps(needs()), "EVENT_NAME": "pull_request"})
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn("ci-gate: PASS", good.stdout)
        bad = self.run_cli({"NEEDS_JSON": json.dumps(needs(overrides={"branch-name": "failure"})), "EVENT_NAME": "pull_request"})
        self.assertEqual(bad.returncode, 1)
        self.assertIn("ci-gate: FAIL", bad.stdout)
        for env in ({}, {"EVENT_NAME": "push"}, {"NEEDS_JSON": "not json", "EVENT_NAME": "push"}, {"NEEDS_JSON": "[]", "EVENT_NAME": "push"}):
            self.assertEqual(self.run_cli(env).returncode, 2, env)

    def test_cli_output_never_contains_event_text(self):
        proc = self.run_cli({"NEEDS_JSON": json.dumps(needs()), "EVENT_NAME": "x\n::error::pwn"})
        self.assertNotIn("pwn", proc.stdout)
        self.assertNotEqual(proc.returncode, 0)  # an unknown event kind is never a pass (PR-only jobs expected skipped)


junit = load("ci_check_junit", "ci_check_junit.py")
corpus = load("ci_corpus_check", "ci_corpus_check.py")


def junit_xml(tests, failures=0, errors=0, skipped=0, wrap=False):
    suite = f'<testsuite name="pytest" tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"></testsuite>'
    return ('<?xml version="1.0"?><testsuites>' + suite + "</testsuites>") if wrap else ('<?xml version="1.0"?>' + suite)


class JunitCheckTests(unittest.TestCase):
    def run_main(self, content, minimum="215", write=True):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.xml")
            if write:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = junit.main([path, minimum])
            return rc, out.getvalue()

    def test_pass_at_and_above_the_floor(self):
        self.assertEqual(self.run_main(junit_xml(215))[0], 0)
        self.assertEqual(self.run_main(junit_xml(230, wrap=True))[0], 0)

    def test_fewer_passed_tests_than_the_floor_fails(self):
        self.assertEqual(self.run_main(junit_xml(214))[0], 1)
        self.assertEqual(self.run_main(junit_xml(0))[0], 1)

    def test_skipped_tests_do_not_count_as_passed(self):
        self.assertEqual(self.run_main(junit_xml(215, skipped=1))[0], 1)

    def test_failures_and_errors_fail_even_above_the_floor(self):
        self.assertEqual(self.run_main(junit_xml(300, failures=1))[0], 1)
        self.assertEqual(self.run_main(junit_xml(300, errors=1))[0], 1)

    def test_bad_input_is_exit_2(self):
        self.assertEqual(self.run_main("not xml")[0], 2)
        self.assertEqual(self.run_main("<root/>")[0], 2)
        self.assertEqual(self.run_main("", write=False)[0], 2)
        self.assertEqual(self.run_main('<!DOCTYPE x [<!ENTITY a "b">]>' + junit_xml(300))[0], 2)
        self.assertEqual(self.run_main(junit_xml(300), minimum="abc")[0], 2)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(junit.main([]), 2)


class CorpusCheckTests(unittest.TestCase):
    PASSING = "import sys\nprint('ssrf cases checked: 1, mismatches: 0')\nsys.exit(0)\n"
    FAILING = "import sys\nprint('MISMATCH x')\nsys.exit(1)\n"

    def tree(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for rel, text in files.items():
            path = os.path.join(tmp.name, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return tmp.name

    def run_check(self, root):
        # GITHUB_STEP_SUMMARY is set in Actions: never let a test fixture write into the real job summary
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            rc = corpus.main([root])
        return rc, out.getvalue()

    def test_no_corpus_is_skipped_not_failed_and_says_so(self):
        rc, out = self.run_check(self.tree({"README.md": "x"}))
        self.assertEqual(rc, 0)
        self.assertIn("SKIPPED", out)
        self.assertNotIn("security-corpus: PASS", out)

    def test_corpus_with_passing_selfcheck_passes(self):
        rc, out = self.run_check(self.tree({"tests/security/corpus/ssrf-urls.json": "{}", "tests/security/corpus/corpus_selfcheck.py": self.PASSING}))
        self.assertEqual(rc, 0, out)
        self.assertIn("security-corpus: PASS", out)

    def test_relative_root_works(self):
        root = self.tree({"c/ssrf-urls.json": "{}", "c/corpus_selfcheck.py": self.PASSING})
        old = os.getcwd()
        os.chdir(os.path.dirname(root))
        try:
            rc, out = self.run_check(os.path.basename(root))
        finally:
            os.chdir(old)
        self.assertEqual(rc, 0, out)

    def test_failing_selfcheck_fails(self):
        rc, out = self.run_check(self.tree({"c/injection-corpus.json": "{}", "c/corpus_selfcheck.py": self.FAILING}))
        self.assertEqual(rc, 1)
        self.assertIn("security-corpus: FAIL", out)

    def test_corpus_without_selfcheck_fails_closed(self):
        rc, out = self.run_check(self.tree({"c/ssrf-urls.json": "{}"}))
        self.assertEqual(rc, 1)
        self.assertIn("missing", out)

    def test_one_bad_directory_fails_even_if_another_passes(self):
        files = {"a/ssrf-urls.json": "{}", "a/corpus_selfcheck.py": self.PASSING, "b/ssrf-urls.json": "{}", "b/corpus_selfcheck.py": self.FAILING}
        self.assertEqual(self.run_check(self.tree(files))[0], 1)

    def test_selfcheck_that_cannot_start_or_times_out_fails(self):
        root = self.tree({"c/ssrf-urls.json": "{}", "c/corpus_selfcheck.py": self.PASSING})
        def boom(*a, **k):
            raise subprocess.TimeoutExpired("x", 1)
        ok, skipped, lines = corpus.run(root, runner=boom)
        self.assertFalse(ok)
        self.assertFalse(skipped)

    def test_hostile_paths_are_sanitised_and_ignored_dirs_skipped(self):
        root = self.tree({"we ird\n::error::x/ssrf-urls.json": "{}", "node_modules/p/ssrf-urls.json": "{}", ".git/x/ssrf-urls.json": "{}"})
        ok, skipped, lines = corpus.run(root)
        text = "\n".join(lines)
        self.assertFalse(ok)
        self.assertEqual(len(lines) - 1, 1)  # one directory + the verdict line; node_modules and .git are not scanned
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("we?ird???error??x: FAIL"), lines[0])  # newline, space and colons are replaced
        self.assertNotIn("\n::error", text)

    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(corpus.main(["a", "b"]), 2)
            self.assertEqual(corpus.main(["/nonexistent-dir-xyz"]), 2)


GOOD_ENV = {
    "DRY_RUN": "true",
    "CI_RUN_ID": "37174591511",
    "CI_RUN_CONCLUSION": "success",
    "CI_RUN_EVENT": "pull_request",
    "CI_RUN_HEAD_SHA": "5" * 40,
    "CI_RUN_HEAD_BRANCH": "chore/KAN-20-ci-enforcement",
    "CI_RUN_PR_NUMBER": "9",
    "GITHUB_REPOSITORY": "ojas005/liferescue",
}


class DryRunTests(unittest.TestCase):
    def run_main(self, env):
        with tempfile.TemporaryDirectory() as tmp:
            full = dict(env, DRYRUN_OUT_DIR=os.path.join(tmp, "out"), GITHUB_STEP_SUMMARY=os.path.join(tmp, "summary.md"))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = dryrun.main(full)
            record, summary = None, None
            rec_path = os.path.join(tmp, "out", "jira-status-dryrun.json")
            if os.path.exists(rec_path):
                with open(rec_path, encoding="utf-8") as fh:
                    record = json.load(fh)
            if os.path.exists(full["GITHUB_STEP_SUMMARY"]):
                with open(full["GITHUB_STEP_SUMMARY"], encoding="utf-8") as fh:
                    summary = fh.read()
        return rc, record, summary

    def test_good_payload_records_what_would_be_posted(self):
        rc, rec, summary = self.run_main(GOOD_ENV)
        self.assertEqual(rc, 0)
        self.assertEqual(rec["marker"], "DRY-RUN, no posting")
        self.assertIs(rec["dry_run"], True)
        self.assertIs(rec["posted"], False)
        self.assertEqual(rec["jira_key"], "KAN-20")
        self.assertEqual(rec["would_post"]["target"], "KAN-20")
        self.assertIsNone(rec["would_post"]["transition"])
        self.assertIn("DRY-RUN, no posting", summary)
        self.assertIn("Nothing was posted", summary)

    def test_refuses_unless_dry_run_is_exactly_true(self):
        for value in (None, "", "false", "TRUE", "True", "1", "true ", "yes"):
            env = dict(GOOD_ENV)
            if value is None:
                del env["DRY_RUN"]
            else:
                env["DRY_RUN"] = value
            rc, rec, summary = self.run_main(env)
            self.assertEqual(rc, 3, value)
            self.assertIsNone(rec)  # nothing written

    def test_branch_without_key_posts_nothing(self):
        for branch in ("main", "zz-test-bad-branch-name", "dependabot/pip/x", "", "feature/KAN-0-x", "Feature/KAN-20-x"):
            rc, rec, _ = self.run_main(dict(GOOD_ENV, CI_RUN_HEAD_BRANCH=branch))
            self.assertEqual(rc, 0, branch)
            self.assertIsNone(rec["would_post"], branch)
            self.assertIsNone(rec["jira_key"], branch)

    def test_hostile_branch_text_is_never_copied(self):
        canary = "EVILTEXT-7c1d"
        for branch in ("feature/KAN-20-x\n::error::" + canary, "feature/KAN-20-`" + canary + "`", "chore/KAN-7-[x](http://" + canary + ")"):
            rc, rec, summary = self.run_main(dict(GOOD_ENV, CI_RUN_HEAD_BRANCH=branch))
            self.assertEqual(rc, 0)
            self.assertNotIn(canary, json.dumps(rec) + summary)
            self.assertIn(rec["jira_key"], ("KAN-20", "KAN-7"))

    def test_invalid_payload_fields_are_rejected_and_values_not_echoed(self):
        canary = "EVILVALUE-3b9e"
        cases = {
            "CI_RUN_ID": "12x" + canary,
            "CI_RUN_CONCLUSION": "success\n::error::" + canary,
            "CI_RUN_EVENT": "Pull Request " + canary,
            "CI_RUN_HEAD_SHA": "z" * 40,
            "GITHUB_REPOSITORY": "no-slash-" + canary,
            "CI_RUN_PR_NUMBER": "0",
        }
        for field, value in cases.items():
            rc, rec, summary = self.run_main(dict(GOOD_ENV, **{field: value}))
            self.assertEqual(rc, 1, field)
            self.assertEqual(rec["status"], "rejected")
            self.assertEqual(rec["invalid_fields"], [field])
            self.assertIsNone(rec["would_post"])
            self.assertNotIn(canary, json.dumps(rec) + summary)

    def test_empty_pr_number_is_allowed(self):
        rc, rec, _ = self.run_main(dict(GOOD_ENV, CI_RUN_PR_NUMBER=""))
        self.assertEqual(rc, 0)
        self.assertIsNone(rec["pr_number"])

    def test_script_cannot_post(self):
        with open(os.path.join(HERE, "ci_jira_status_dryrun.py"), encoding="utf-8") as fh:
            src = fh.read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        for needle in ("import urllib", "import http", "import socket", "import requests", "import subprocess", "os.system", "urlopen", "Authorization", "JIRA_", "secrets."):
            self.assertNotIn(needle, code, needle)


if __name__ == "__main__":
    unittest.main()
