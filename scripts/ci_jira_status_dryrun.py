#!/usr/bin/env python3
"""DRY-RUN stub: record what the CI -> Jira status reporter WOULD post. It never posts anything.

PLACEHOLDER. LR 04's Jira reporting module is not in this repository yet. This script has no Jira
client, no network access, no subprocess and reads no credentials, so it cannot post by
construction. When LR 04's module lands, LR 10 replaces the body of build_record() with a call to
that module in its mock/dry-run mode; the DRY_RUN guard below and the "no secrets" rule stay.

Input (environment only; all values come from a workflow_run payload and are UNTRUSTED):
  DRY_RUN              must be exactly "true", otherwise the script refuses to run (exit 3)
  CI_RUN_ID            digits
  CI_RUN_CONCLUSION    one of the GitHub conclusions (success, failure, cancelled, ...)
  CI_RUN_EVENT         event that started the CI run (pull_request, push, ...)
  CI_RUN_HEAD_SHA      40 hex characters
  CI_RUN_HEAD_BRANCH   branch name; ONLY used to extract a KAN-<n> key with a fixed pattern
  CI_RUN_PR_NUMBER     optional, digits (the first pull request of the run, if any)
  GITHUB_REPOSITORY    owner/name (set by the runner)
  DRYRUN_OUT_DIR       output directory (default: jira-dryrun)
  GITHUB_STEP_SUMMARY  optional; when set, a fixed-format summary is appended

Output: <out>/jira-status-dryrun.json and a job summary. Free text from the payload (branch name)
is never copied into either: only the validated Jira key and fixed words are.
Exit code: 0 record written; 1 a payload field was invalid (record written with status "rejected",
field NAMES only); 3 DRY_RUN is not "true" (nothing written).
"""
import json
import os
import re
import sys

MARKER = "DRY-RUN, no posting"
CONCLUSIONS = {
    "success", "failure", "cancelled", "skipped", "neutral", "timed_out",
    "action_required", "stale", "startup_failure",
}
KEY_FROM_BRANCH = re.compile(r"(?:feature|bugfix|security|chore|docs)/(KAN-[1-9][0-9]{0,8})-")
RUN_ID = re.compile(r"[0-9]{1,20}")
SHA = re.compile(r"[0-9a-f]{40}")
EVENT = re.compile(r"[a-z_]{1,40}")
REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
PR_NUMBER = re.compile(r"[1-9][0-9]{0,9}")


def build_record(env):
    """Pure function: env mapping -> (record dict, exit code). No I/O."""
    run_id, conclusion = env.get("CI_RUN_ID", ""), env.get("CI_RUN_CONCLUSION", "")
    event, sha = env.get("CI_RUN_EVENT", ""), env.get("CI_RUN_HEAD_SHA", "")
    repo, pr = env.get("GITHUB_REPOSITORY", ""), env.get("CI_RUN_PR_NUMBER", "")
    bad = []
    if RUN_ID.fullmatch(run_id) is None:
        bad.append("CI_RUN_ID")
    if conclusion not in CONCLUSIONS:
        bad.append("CI_RUN_CONCLUSION")
    if EVENT.fullmatch(event) is None:
        bad.append("CI_RUN_EVENT")
    if SHA.fullmatch(sha) is None:
        bad.append("CI_RUN_HEAD_SHA")
    if REPO.fullmatch(repo) is None:
        bad.append("GITHUB_REPOSITORY")
    if pr != "" and PR_NUMBER.fullmatch(pr) is None:
        bad.append("CI_RUN_PR_NUMBER")
    base = {"marker": MARKER, "dry_run": True, "reporter": "STUB (LR 04 Jira module not present)", "posted": False}
    if bad:
        base.update({"status": "rejected", "invalid_fields": sorted(bad), "would_post": None})
        return base, 1
    # Re.match on the branch: fixed pattern, takes at most the key; nothing else of the branch is kept.
    m = KEY_FROM_BRANCH.match(env.get("CI_RUN_HEAD_BRANCH", ""))
    key = m.group(1) if m else None
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    base.update({
        "status": "recorded",
        "ci_run": {"id": run_id, "event": event, "conclusion": conclusion, "head_sha": sha, "url": run_url},
        "pr_number": int(pr) if pr else None,
        "jira_key": key,
    })
    if key is None:
        base["would_post"] = None
        base["note"] = "no Jira key in the branch name; nothing would be posted"
    else:
        base["would_post"] = {
            "target": key,
            "kind": "comment",
            "text": f"CI {conclusion} for commit {sha[:7]} ({event}): {run_url}",
            "transition": None,
        }
    return base, 0


def summary_lines(record):
    lines = [f"### CI to Jira status - {MARKER}", "", "Nothing was posted to Jira. This is a stub; no Jira credentials exist in this workflow.", ""]
    if record["status"] == "rejected":
        lines.append("Record REJECTED. Invalid payload fields: " + ", ".join(f"`{f}`" for f in record["invalid_fields"]))
        return lines
    run = record["ci_run"]
    lines += [
        f"- CI run `{run['id']}`: event `{run['event']}`, conclusion `{run['conclusion']}`, head `{run['head_sha'][:7]}`",
        f"- Jira key from branch: `{record['jira_key']}`" if record["jira_key"] else "- Jira key from branch: none",
    ]
    wp = record["would_post"]
    lines.append(f"- WOULD post to `{wp['target']}`: `{wp['text']}`" if wp else "- WOULD post: nothing")
    return lines


def main(environ=None):
    env = os.environ if environ is None else environ
    if env.get("DRY_RUN") != "true":
        print("error: refusing to run: DRY_RUN must be exactly 'true' (real posting is not implemented)", file=sys.stderr)
        return 3
    record, rc = build_record(env)
    out_dir = env.get("DRYRUN_OUT_DIR", "jira-dryrun")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "jira-status-dryrun.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
        fh.write("\n")
    lines = summary_lines(record)
    print(f"{MARKER}: status={record['status']} (see jira-status-dryrun.json)")
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
