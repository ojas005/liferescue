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

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci_gate = load("ci_gate", "ci_gate.py")
dryrun = load("ci_jira_status_dryrun", "ci_jira_status_dryrun.py")


def needs(node=False, python=False, overrides=None, detect_result="success"):
    """A `needs` object as the runner would provide it for a run with no failures."""
    n = {
        "secret-scan": {"result": "success", "outputs": {}},
        "repo-validation": {"result": "success", "outputs": {}},
        "detect": {"result": detect_result, "outputs": {"node": str(node).lower(), "python": str(python).lower()}},
        "python-unit-tests": {"result": "success", "outputs": {}},
        "branch-name": {"result": "success", "outputs": {}},
        "pr-link-check": {"result": "success", "outputs": {}},
        "node-checks": {"result": "success" if node else "skipped", "outputs": {}},
        "python-checks": {"result": "success" if python else "skipped", "outputs": {}},
        "dependency-scan": {"result": "success" if (node or python) else "skipped", "outputs": {}},
        "sbom": {"result": "success" if (node or python) else "skipped", "outputs": {}},
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

    def test_conditional_jobs_active_and_successful(self):
        self.assertTrue(self.ok(needs(node=True, python=True)))

    def test_every_required_job_failing_fails_the_gate(self):
        for job in list(needs()):
            for bad in ("failure", "cancelled", "skipped"):
                if needs()[job]["result"] == bad:
                    continue  # that is the legitimate value
                with self.subTest(job=job, bad=bad):
                    self.assertFalse(self.ok(needs(overrides={job: bad})))

    def test_skipped_required_job_is_not_a_pass(self):
        for job in ("secret-scan", "repo-validation", "detect", "python-unit-tests", "branch-name", "pr-link-check"):
            self.assertFalse(self.ok(needs(overrides={job: "skipped"})), job)

    def test_pr_only_job_must_be_skipped_on_push(self):
        self.assertFalse(self.ok(needs(), "push"))
        self.assertFalse(self.ok(push_needs(overrides={"branch-name": "success"}), "push"))

    def test_conditional_job_that_should_run_but_is_skipped_fails(self):
        self.assertFalse(self.ok(needs(node=True, overrides={"node-checks": "skipped"})))
        self.assertFalse(self.ok(needs(python=True, overrides={"python-checks": "skipped"})))

    def test_conditional_job_failure_fails(self):
        self.assertFalse(self.ok(needs(node=True, overrides={"node-checks": "failure"})))
        self.assertFalse(self.ok(needs(python=True, overrides={"dependency-scan": "failure"})))

    def test_conditional_job_ran_although_detect_said_no_fails(self):
        self.assertFalse(self.ok(needs(overrides={"sbom": "success"})))

    def test_detect_not_successful_or_odd_outputs_fail(self):
        self.assertFalse(self.ok(needs(detect_result="failure")))
        n = needs()
        n["detect"]["outputs"]["node"] = ""
        self.assertFalse(self.ok(n))
        n = needs()
        del n["detect"]["outputs"]
        self.assertFalse(self.ok(n))

    def test_missing_job_and_unknown_job_fail(self):
        self.assertFalse(self.ok(needs(overrides={"secret-scan": None})))
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
