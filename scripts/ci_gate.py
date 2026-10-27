#!/usr/bin/env python3
"""Decision logic of the always-run `ci-gate` job in .github/workflows/ci.yml.

The gate is the ONE check to require in branch protection: GitHub counts a skipped required job as
passing, so required checks must not be the individual jobs. This script fails closed: anything it
does not positively recognise is a failure.

Input (environment only; no arguments):
  NEEDS_JSON   toJSON(needs) of the gate job: {"<job id>": {"result": "...", "outputs": {...}}, ...}
  EVENT_NAME   github.event_name

Rules:
  * ALWAYS jobs must have result "success" on every event.
  * PR_ONLY jobs (`if: github.event_name == 'pull_request'`) must be "success" on pull_request and
    "skipped" on any other event.
  * CONDITIONAL jobs run only when the `detect` job found project files. They must be "success"
    when detect says "true" and "skipped" when detect says "false". Any other detect output
    (missing, empty, odd) is a failure, and so is a detect job that did not succeed.
  * A job id that is missing from `needs`, or present but not known here, is a failure (adding a job
    to `needs:` without teaching the gate must not be silently accepted).
Exit code: 0 all rules hold; 1 otherwise; 2 bad input.
Only fixed job ids and the five runner result words are ever printed.
"""

import json
import os
import sys

ALWAYS = ("secret-scan", "repo-validation", "detect", "python-unit-tests")
PR_ONLY = ("branch-name", "pr-link-check")
# job id -> detect outputs of which at least one must be "true" for the job to run
CONDITIONAL = {
    "node-checks": ("node",),
    "python-checks": ("python",),
    "dependency-scan": ("node", "python"),
    "sbom": ("node", "python"),
}
RESULTS = {"success", "failure", "cancelled", "skipped"}


def _result(needs, job):
    entry = needs.get(job)
    res = entry.get("result") if isinstance(entry, dict) else None
    return res if res in RESULTS else None


def evaluate(needs, event_name):
    """Return (ok, list of (job, expected, actual, passed))."""
    rows = []

    def check(job, expected, actual):
        rows.append(
            (job, expected, actual if actual else "missing/unknown", actual == expected)
        )

    for job in ALWAYS:
        check(job, "success", _result(needs, job))
    for job in PR_ONLY:
        check(
            job,
            "success" if event_name == "pull_request" else "skipped",
            _result(needs, job),
        )
    detect = needs.get("detect") if isinstance(needs.get("detect"), dict) else {}
    outputs = detect.get("outputs") if isinstance(detect.get("outputs"), dict) else {}
    for job, keys in CONDITIONAL.items():
        values = [outputs.get(k) for k in keys]
        if _result(needs, "detect") != "success" or any(
            v not in ("true", "false") for v in values
        ):
            rows.append(
                (
                    job,
                    "detect succeeded with true/false outputs",
                    "detect unusable",
                    False,
                )
            )
            continue
        check(job, "success" if "true" in values else "skipped", _result(needs, job))
    known = set(ALWAYS) | set(PR_ONLY) | set(CONDITIONAL)
    for job in sorted(set(needs) - known):
        rows.append(
            ("<unknown job id>", "listed in ci_gate.py", "present in needs", False)
        )
    return all(r[3] for r in rows), rows


def main(argv=None, environ=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    env = os.environ if environ is None else environ
    if argv:
        print("error: this script takes no arguments", file=sys.stderr)
        return 2
    try:
        needs = json.loads(env["NEEDS_JSON"])
        event_name = env["EVENT_NAME"]
        if not isinstance(needs, dict):
            raise ValueError("NEEDS_JSON is not an object")
    except (KeyError, ValueError):
        print(
            "error: NEEDS_JSON (JSON object) and EVENT_NAME are required",
            file=sys.stderr,
        )
        return 2
    ok, rows = evaluate(needs, event_name)
    event_shown = event_name if event_name in ("pull_request", "push") else "other"
    lines = [
        f"ci-gate (event kind: {event_shown})",
        "",
        "| job | expected | actual | ok |",
        "|---|---|---|---|",
    ]
    lines += [f"| {j} | {e} | {a} | {'yes' if p else 'NO'} |" for j, e, a, p in rows]
    lines += ["", "ci-gate: PASS" if ok else "ci-gate: FAIL"]
    print("\n".join(lines))
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
