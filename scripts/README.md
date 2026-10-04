# scripts/

**Purpose:** repository automation scripts (CI helpers, local development helpers).

**Source:** doc 19 Step 2 (directory skeleton).

**Status:** currently contains the repository validation scripts (the first two are used by `.github/workflows/ci.yml`; the branch-name validator is not wired into CI yet):

- `validate-repo-structure.sh` - checks required files/directories and the baseline manifest.
- `check-markdown-links.py` - checks that relative links in Markdown files resolve.
- `check-branch-name.py` - validates a branch name against `<type>/KAN-<number>-<description>` (KAN-20). Usage: `python3 scripts/check-branch-name.py <branch>` or set `BRANCH_NAME`. Exit code 0 valid, 1 invalid, 2 no name given. Standard library only; the name is never evaluated or passed to a shell.
- `test_check_branch_name.py` - unit tests for it: `python3 -m unittest -v scripts/test_check_branch_name.py`.
