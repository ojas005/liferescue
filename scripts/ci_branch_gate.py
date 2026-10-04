#!/usr/bin/env python3
"""CI gate for pull-request branch names (KAN-20): the CI-facing wrapper around check-branch-name.py.

It adds exactly one thing to scripts/check-branch-name.py: the CI exemptions. Everything else is
delegated to `validate()` of that script, so the rule (<type>/KAN-<number>-<description>) lives in
one place only.

Input (environment only; no arguments - any argument is a usage error, exit 2):
  BRANCH_NAME        the PR head ref. Untrusted. The workflow maps ONLY the branch name into this.
  PR_AUTHOR_LOGIN    optional. Login of the PR author, used ONLY to decide the dependabot exemption.
                     Unset or anything other than "dependabot[bot]" means: no dependabot exemption.

Exemptions (all other names must pass validate()):
  1. EXACT_EXEMPTIONS: the listed legacy names, compared with == on the whole string (no prefix,
     no case folding, no normalization, no trailing-newline tolerance).
  2. dependabot/*: only when the PR author is dependabot[bot] AND the name is made of safe
     characters. A human cannot get a free pass by naming a branch "dependabot/x".

Output: fixed text only. The branch name is never echoed by this wrapper; the only place it may
appear is the escaped, length-bounded text printed by check-branch-name.py (ascii(), single line,
at most 120 characters, always printed after a fixed "INVALID:" / "OK:" prefix, so it can never start
a line and therefore can never form a workflow command such as ::error::). The wrapper itself
prints the workflow command "::error title=..." with a FIXED message and no attacker text.

Exit code: 0 valid or exempt, 1 invalid, 2 BRANCH_NAME unset or an argument was given.
Standard library only; no network, no subprocess, the name is never evaluated.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Names that are valid for CI although they do not follow the rule. Compared with ==, whole string.
# Keep this list SHORT and reviewed: every entry is a permanent hole in the rule.
EXACT_EXEMPTIONS = {
    # PR #1 "chore: repository bootstrap baseline", merged 2026-10-03 (before the rule existed).
    "chore/bootstrap-repository-baseline": "legacy: bootstrap baseline branch (PR #1, merged)",
    # PR #2 "docs: agent assignment registry for KAN-4..KAN-55", merged 2026-10-04; no issue number in the name.
    "docs/KAN-orchestration-agent-assignment-registry": "legacy: agent assignment registry branch (PR #2, merged)",
    # The other merged PR branches (#3 docs/KAN-20-contributing-branch-rules, #4 feature/KAN-20-branch-name-validator,
    # #5 feature/KAN-20-transition-allowlist, #8 docs/KAN-20-crosslinks) already satisfy the rule: no entry needed.
}

DEPENDABOT_AUTHOR = "dependabot[bot]"
DEPENDABOT_NAME = re.compile(r"dependabot/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
DEPENDABOT_MAX_LENGTH = 200


def _load_validator():
    spec = importlib.util.spec_from_file_location("check_branch_name", os.path.join(HERE, "check-branch-name.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify(name, author, validator):
    """Return ("valid"|"exempt"|"invalid", fixed_reason_text). Never includes `name` in the reason."""
    if not isinstance(name, str):
        return "invalid", "branch name is not text"
    if name in EXACT_EXEMPTIONS:
        return "exempt", EXACT_EXEMPTIONS[name]
    if (
        author == DEPENDABOT_AUTHOR
        and len(name) <= DEPENDABOT_MAX_LENGTH
        and ".." not in name
        and DEPENDABOT_NAME.fullmatch(name) is not None
    ):
        return "exempt", "dependabot branch opened by dependabot[bot]"
    reason = validator.validate(name)
    if reason is None:
        return "valid", "matches <type>/KAN-<number>-<description>"
    return "invalid", reason


def main(argv=None, environ=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    environ = os.environ if environ is None else environ
    if argv:
        print("error: this script takes no arguments; set the environment variable BRANCH_NAME", file=sys.stderr)
        return 2
    if "BRANCH_NAME" not in environ:
        print("error: no branch name given; set the environment variable BRANCH_NAME", file=sys.stderr)
        return 2
    validator = _load_validator()
    name = environ["BRANCH_NAME"]
    verdict, reason = classify(name, environ.get("PR_AUTHOR_LOGIN"), validator)
    if verdict == "exempt":
        print(f"EXEMPT: {reason}")
        return 0
    if verdict == "valid":
        print(f"OK: branch name {validator.escaped(name)} is valid")
        return 0
    # Invalid. Re-use the validator's own (escaped, bounded) explanation, then add a FIXED annotation.
    validator.main([], {"BRANCH_NAME": name})
    print("::error title=Branch name::The PR branch name does not follow <type>/KAN-<number>-<description>. See CONTRIBUTING.md (Branching).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
