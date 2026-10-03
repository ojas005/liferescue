# scripts/

**Purpose:** repository automation scripts (CI helpers, local development helpers).

**Source:** doc 19 Step 2 (directory skeleton).

**Status:** currently contains the repository validation scripts used by `.github/workflows/ci.yml`:

- `validate-repo-structure.sh` - checks required files/directories and the baseline manifest.
- `check-markdown-links.py` - checks that relative links in Markdown files resolve.
