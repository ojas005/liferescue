# scripts/

**Purpose:** repository automation scripts (CI helpers, local development helpers).

**Source:** doc 19 Step 2 (directory skeleton).

**Status:** currently contains the repository validation scripts (the first two are used by `.github/workflows/ci.yml`; the branch-name validator is not wired into CI yet):

- `validate-repo-structure.sh` - checks required files/directories and the baseline manifest.
- `check-markdown-links.py` - checks that relative links in Markdown files resolve.
- `check-branch-name.py` - validates a branch name against `<type>/KAN-<number>-<description>` (KAN-20). Usage: set the environment variable `BRANCH_NAME` and run `python3 scripts/check-branch-name.py` (no arguments; in CI pass the name through `env:`, never by interpolating it into the command line). The script has no options: any argument, including `-h` and `--help`, is a usage error. Exit code 0 valid, 1 invalid (an empty value is invalid), 2 `BRANCH_NAME` not set or an argument was given; a CI step must treat any non-zero exit code as failure. The name is echoed back escaped and at most 120 characters. Standard library only; the name is never evaluated or passed to a shell. The whole name must match: the script uses `re.fullmatch` because a `$` anchor alone would accept a trailing newline in some engines (Perl/PCRE, Python `re.match`/`re.search`, line-based `grep`), and it applies no Unicode normalization (NFKC would let full-width characters and look-alikes through, so they are rejected as given).
- `test_check_branch_name.py` - unit tests for it (including argument refusal, bounded output and mutation checks): `python3 -m unittest -v scripts/test_check_branch_name.py`.
- `check_transition.py` - pure-logic Jira transition allowlist checker (KAN-20, WI-04-6): `python3 scripts/check_transition.py --validate-allowlist` or `--request request.json`. No agent or automation path reaches Done. Standard library only; no Jira or network calls. Importable as a module for KAN-26/KAN-27.
- `jira-transition-allowlist.json` - the machine-readable allowlist (statuses, actors, evidence, `exec-rework` rules). See [`docs/jira-transition-allowlist.md`](../docs/jira-transition-allowlist.md).
- `test_check_transition.py` - unit tests for both: `python3 -m unittest -v scripts/test_check_transition.py`.
