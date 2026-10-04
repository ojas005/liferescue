#!/usr/bin/env python3
"""Static guards for .github/workflows/*.yml (KAN-20): the security rules of the workflows as tests.

Run from the repository root:  python3 -m unittest -v scripts/test_workflow_guards.py

Standard library only, so the YAML is read with a small line scanner (not a YAML parser): it relies on
the two-space layout used in this repository. actionlint (run separately) is the syntax authority.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF_DIR = os.path.join(ROOT, ".github", "workflows")
NEW_JOBS = ("branch-name", "python-unit-tests", "pr-link-check", "ci-gate")  # added by KAN-20 in ci.yml
PER_PACKAGE_JOBS = ("contract-tests", "arch-check")  # CI-PERPKG: bound to packages/contract, enabled by detect output `contract`
APPROVED_ACTIONS = {  # the only SHAs in use (verified via the GitHub API); a new action or SHA must be added here on purpose
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}
CI_DIR = os.path.join(ROOT, ".github", "ci")
UNTRUSTED = re.compile(
    r"github\.head_ref|github\.event\.workflow_run\.(head_branch|head_commit|display_title|head_repository|pull_requests)"
    r"|github\.event\.(pull_request|issue|comment|review|head_commit|commits)\.(title|body|head\.ref|head\.label|head\.repo)"
    r"|github\.event\.pages|github\.event\.discussion|github\.event\.release\.(name|body)"
)
ENV_LINE = re.compile(r"^\s+[A-Z][A-Z0-9_]*: \$\{\{ [^}]+ \}\}\s*$")


def read(name):
    with open(os.path.join(WF_DIR, name), encoding="utf-8") as fh:
        return fh.read().splitlines()


def code_lines(lines):
    return [l for l in lines if not l.lstrip().startswith("#")]


def workflows():
    return sorted(f for f in os.listdir(WF_DIR) if f.endswith((".yml", ".yaml")))


def jobs(lines):
    """job id -> list of lines of that job block (jobs: section, two-space layout)."""
    out, current, in_jobs = {}, None, False
    for line in lines:
        if re.match(r"^jobs:\s*$", line):
            in_jobs, current = True, None
            continue
        if in_jobs and re.match(r"^\S", line) and not line.startswith("#"):
            in_jobs, current = False, None
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if in_jobs and m:
            current = m.group(1)
            out[current] = []
        elif in_jobs and current:
            out[current].append(line)
    return out


def run_blocks(lines):
    """Yield (line number, text) for every line that belongs to a `run:` value."""
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)(- )?run:\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        key_col = len(m.group(1)) + (2 if m.group(2) else 0)
        value = m.group(3)
        if re.match(r"^[|>][+-]?\s*(#.*)?$", value):
            j = i + 1
            while j < len(lines) and (lines[j].strip() == "" or len(lines[j]) - len(lines[j].lstrip()) > key_col):
                yield j + 1, lines[j]
                j += 1
            i = j
        else:
            yield i + 1, value
            i += 1


class WorkflowGuards(unittest.TestCase):
    def test_there_are_workflows(self):
        self.assertIn("ci.yml", workflows())
        self.assertIn("ci-jira-status.yml", workflows())

    def test_no_expression_interpolation_inside_run(self):
        for wf in workflows():
            for n, text in run_blocks(read(wf)):
                self.assertNotIn("${{", text, f"{wf}:{n}: expression inside run: (pass it through env instead)")

    def test_untrusted_context_only_in_env_assignments(self):
        for wf in workflows():
            for n, line in enumerate(code_lines(read(wf)), 1):
                if UNTRUSTED.search(line):
                    self.assertRegex(line, ENV_LINE, f"{wf}: untrusted context outside an env assignment: {line.strip()}")

    def test_branch_name_job_maps_only_the_branch_name(self):
        block = jobs(read("ci.yml"))["branch-name"]
        mapped = [l.strip() for l in block if "${{" in l]
        self.assertEqual(
            mapped,
            ["BRANCH_NAME: ${{ github.head_ref }}", "PR_AUTHOR_LOGIN: ${{ github.event.pull_request.user.login }}"],
        )
        self.assertIn("if: github.event_name == 'pull_request'", "\n".join(l.strip() for l in block))

    def test_pr_link_job_maps_text_only_through_env(self):
        block = jobs(read("ci.yml"))["pr-link-check"]
        mapped = sorted(l.strip() for l in block if "${{" in l)
        self.assertEqual(mapped, sorted([
            "PR_TITLE: ${{ github.event.pull_request.title }}",
            "PR_BODY: ${{ github.event.pull_request.body }}",
            "PR_BRANCH: ${{ github.event.pull_request.head.ref }}",
            "BRANCH_NAME: ${{ github.event.pull_request.head.ref }}",
            "PR_AUTHOR_LOGIN: ${{ github.event.pull_request.user.login }}",
        ]))
        text = "\n".join(block)
        self.assertIn("python3 scripts/check_pr_link.py", text)
        self.assertIn("PLACEHOLDER", text)

    def test_pull_request_types_include_edited(self):
        self.assertIn("types: [opened, synchronize, reopened, edited]", "\n".join(read("ci.yml")))

    def test_no_pull_request_target_no_secrets_no_inputs(self):
        for wf in workflows():
            text = "\n".join(code_lines(read(wf)))
            for needle in ("pull_request_target", "secrets.", "workflow_dispatch", "inputs.", "github.event.inputs", "vars."):
                self.assertNotIn(needle, text, f"{wf}: {needle}")

    def test_permissions_and_timeouts(self):
        for wf in workflows():
            lines = read(wf)
            self.assertTrue(any(re.match(r"^permissions:", l) for l in lines), f"{wf}: no top-level permissions")
            for job, block in jobs(lines).items():
                self.assertTrue(any("timeout-minutes:" in l for l in block), f"{wf}:{job}: no timeout-minutes")
                self.assertTrue(any(re.match(r"^    permissions:", l) for l in block), f"{wf}:{job}: no job-level permissions")

    def test_ci_top_level_permissions_are_read_only(self):
        text = "\n".join(read("ci.yml"))
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read\n")
        self.assertNotRegex(text, r"(?m)^\s+(write|admin)\b")
        self.assertNotRegex(text, r": write\b")

    def test_only_approved_action_shas_are_used(self):
        for wf in workflows():
            for u in re.findall(r"uses:\s*(\S+)", "\n".join(code_lines(read(wf)))):
                self.assertIn(u, APPROVED_ACTIONS, f"{wf}: {u} (verify a new SHA via the GitHub API, then add it on purpose)")

    def test_no_root_level_python_or_node_jobs(self):
        all_jobs = jobs(read("ci.yml"))
        for gone in ("node-checks", "python-checks", "dependency-scan", "sbom"):
            self.assertNotIn(gone, all_jobs, gone)
        text = "\n".join(code_lines(read("ci.yml")))
        # detect exposes exactly the explicit per-package flags; no glob over pyproject.toml/package.json drives a job
        self.assertEqual(re.findall(r"(?m)^      ([a-z-]+): \$\{\{ steps\.d\.outputs\.\1 \}\}$", text), ["contract"])
        self.assertIn("packages/contract/pyproject.toml", text)
        for forbidden in ("npx", "npm ci", "npm install", "pip install -e .\n", "ruff format --check .\n"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_per_package_jobs_are_bound_to_detect_and_their_package(self):
        all_jobs = jobs(read("ci.yml"))
        for job in PER_PACKAGE_JOBS:
            block = "\n".join(all_jobs[job])
            self.assertIn("    needs: detect\n", block, job)
            self.assertIn("    if: needs.detect.outputs.contract == 'true'\n", block, job)
            self.assertNotIn("always()", block, job)

    def test_python_tools_run_only_inside_a_package_or_with_explicit_paths(self):
        # every ruff/mypy/pytest invocation in ci.yml sits in a step with working-directory: packages/contract
        text = "\n".join(code_lines(read("ci.yml")))
        steps = re.split(r"(?m)^      - ", text)
        seen = 0
        for st in steps:
            if re.search(r"-m (ruff|mypy|pytest)\b|^\s*(ruff|mypy|pytest)\b", st, re.MULTILINE):
                seen += 1
                self.assertIn("working-directory: packages/contract", st, st[:80])
        self.assertGreaterEqual(seen, 4)

    def test_pip_installs_are_hash_locked_or_local(self):
        for wf in workflows():
            for n, text in run_blocks(read(wf)):
                if "pip install" in text:
                    ok = ("--require-hashes" in text and "--no-deps" in text and " -r .github/ci/" in text) or \
                         ("--no-deps" in text and "--no-build-isolation" in text and "-e packages/contract" in text)
                    self.assertTrue(ok, f"{wf}:{n}: pip install must be hash-locked (-r .github/ci/*.txt) or the local package: {text.strip()}")

    def test_lock_files_are_fully_pinned_with_hashes(self):
        for name in ("contract-requirements.txt", "audit-requirements.txt"):
            with open(os.path.join(CI_DIR, name), encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            reqs = [i for i, l in enumerate(lines) if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*==", l)]
            self.assertGreater(len(reqs), 10, name)
            for i in reqs:
                block = [lines[i]]
                j = i + 1
                while j < len(lines) and lines[j].startswith("    --hash="):
                    block.append(lines[j])
                    j += 1
                self.assertGreaterEqual(len(block), 2, f"{name}: {lines[i]} has no --hash")
            self.assertFalse([l for l in lines if re.match(r"^[A-Za-z]", l) and "==" not in l], name)
        for name in ("contract.in", "audit.in"):
            self.assertTrue(os.path.exists(os.path.join(CI_DIR, name)), name)

    def test_dependency_audit_is_report_only_and_tolerates_absent_inputs(self):
        block = "\n".join(code_lines(jobs(read("ci.yml"))["dependency-audit"]))
        self.assertNotIn("exit 1", block)
        self.assertNotIn("continue-on-error", block)
        self.assertIn("if python3 -m pip_audit", block)
        self.assertIn("if (cd ", block)
        self.assertIn("steps.locks.outputs.npm != '0'", block)  # setup-node only when a package-lock.json is tracked
        self.assertIn("nothing to audit", block)

    def test_ruff_full_check_blocking_switch_exists_and_defaults_to_report_only(self):
        text = "\n".join(code_lines(read("ci.yml")))
        self.assertIn('RUFF_FULL_BLOCKING: "false"', text)
        self.assertIn('[ "$RUFF_FULL_BLOCKING" = "true" ]', text)
        self.assertIn("--isolated --no-cache --select E9,F63,F7,F82", text)  # the blocking subset stays blocking

    def test_every_action_is_pinned_by_full_sha_and_checkout_drops_credentials(self):
        for wf in workflows():
            text = "\n".join(code_lines(read(wf)))
            uses = re.findall(r"uses:\s*(\S+)", text)
            self.assertTrue(uses)
            for u in uses:
                self.assertRegex(u, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", f"{wf}: {u}")
            self.assertEqual(text.count("actions/checkout@"), text.count("persist-credentials: false"), wf)

    def test_no_job_swallows_failures(self):
        lines = read("ci.yml")
        for job in jobs(lines):
            text = "\n".join(code_lines(jobs(lines)[job]))
            for needle in ("|| true", "|| :", "continue-on-error", "set +e"):
                self.assertNotIn(needle, text, f"{job}: {needle}")
        self.assertNotIn("|| true", "\n".join(code_lines(read("ci-jira-status.yml"))))

    def test_job_names_are_stable(self):
        for wf in workflows():
            for line in read(wf):
                if re.match(r"^\s+name:", line):
                    for word in ("ACTIVE", "CONDITIONAL", "inactive", "unpinned"):
                        self.assertNotIn(word, line, f"{wf}: {line.strip()}")

    def test_concurrency_cancels_only_pull_requests(self):
        text = "\n".join(read("ci.yml"))
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", text)
        self.assertNotIn("cancel-in-progress: true", text)
        self.assertIn("cancel-in-progress: false", "\n".join(read("ci-jira-status.yml")))

    def test_ci_gate_needs_every_other_job_and_always_runs(self):
        lines = read("ci.yml")
        all_jobs = jobs(lines)
        gate = all_jobs["ci-gate"]
        needed = []
        grab = False
        for l in gate:
            if re.match(r"^    needs:", l):
                grab = True
                continue
            if grab:
                m = re.match(r"^      - ([A-Za-z0-9_-]+)\s*$", l)
                if not m:
                    break
                needed.append(m.group(1))
        self.assertEqual(sorted(needed), sorted(set(all_jobs) - {"ci-gate"}))
        self.assertIn("    if: always()", gate)
        self.assertIn("    name: CI gate", gate)

    def test_ci_gate_script_knows_every_job(self):
        spec_path = os.path.join(ROOT, "scripts", "ci_gate.py")
        with open(spec_path, encoding="utf-8") as fh:
            src = fh.read()
        for job in jobs(read("ci.yml")):
            if job != "ci-gate":
                self.assertIn(f'"{job}"', src, job)

    def test_ci_gate_job_sets_match_the_workflow_exactly(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ci_gate_for_guard", os.path.join(ROOT, "scripts", "ci_gate.py"))
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        known = set(gate.ALWAYS) | set(gate.PR_ONLY) | set(gate.REPORT_ONLY) | set(gate.CONDITIONAL)
        self.assertEqual(known, set(jobs(read("ci.yml"))) - {"ci-gate"})
        self.assertEqual(set(gate.CONDITIONAL), set(PER_PACKAGE_JOBS))

    def test_jira_workflow_is_dry_run_and_does_not_run_pr_code(self):
        lines = read("ci-jira-status.yml")
        code = "\n".join(code_lines(lines))
        self.assertIn("workflow_run:", code)
        self.assertIn('DRY_RUN: "true"', code)
        self.assertRegex(code, r"(?m)^permissions: \{\}\s*$")
        job = "\n".join(code_lines(jobs(lines)["jira-status-dry-run"]))
        self.assertIn("      contents: read", job)
        for needle in ("actions: ", "pull-requests:", "issues:", "write"):
            self.assertNotIn(needle, job)
        # the checkout takes no `ref:` (= default branch); PR head code is never fetched or run
        self.assertNotRegex(code, r"(?m)^\s+ref:")
        self.assertNotIn("head_sha }}\n          path", code)
        self.assertNotIn("download-artifact", code)
        self.assertNotIn("repository:", code)
        self.assertNotIn("gh ", code)
        self.assertNotIn("curl", code)

    def test_triggers_have_no_dangerous_events(self):
        for wf in workflows():
            lines, events, in_on = read(wf), set(), False
            for l in lines:
                if re.match(r"^on:\s*$", l):
                    in_on = True
                    continue
                if in_on and re.match(r"^\S", l) and not l.startswith("#"):
                    break
                m = re.match(r"^  ([a-z_]+):", l)
                if in_on and m:
                    events.add(m.group(1))
            self.assertTrue(events, wf)
            self.assertFalse(events & {"pull_request_target", "issue_comment", "issues", "repository_dispatch", "workflow_dispatch"}, wf)


if __name__ == "__main__":
    unittest.main()
