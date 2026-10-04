#!/usr/bin/env python3
"""Security-corpus consistency check for the `security-corpus` CI job (LR 07 request; LR 08 items S7 and U8; owner LR 10).

The corpora (`ssrf-urls.json`, `injection-corpus.json`) ship with a stdlib self-check, `corpus_selfcheck.py`, that proves the
labels agree with an independent classifier. This script finds every directory of the working tree that holds a corpus file
and runs the self-check there. It does NOT test product code: the SSRF guard (`safe_fetch`) and the injection invariants I1-I6
are exercised by the product test suites, not here (see .github/ci/README.md, "Not covered").

Behaviour (fail closed, but only when corpus files exist):
  * no corpus file anywhere                          -> notice + SKIPPED line, exit 0 (the corpora are not on the branch yet)
  * a directory has a corpus file but no self-check  -> FAIL
  * a self-check exits non-zero / times out / cannot start -> FAIL
  * all self-checks exit 0                           -> PASS
Usage: python3 scripts/ci_corpus_check.py [repository root]   (default: current directory)
Exit code: 0 pass or skipped; 1 failure; 2 usage error. Only repository-relative paths are printed, sanitised.
"""
import os
import re
import subprocess
import sys

CORPUS_FILES = ("ssrf-urls.json", "injection-corpus.json")
SELFCHECK = "corpus_selfcheck.py"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
TIMEOUT_SECONDS = 120


def safe(text):
    return re.sub(r"[^A-Za-z0-9._/-]", "?", text)[:200]


def find_corpus_dirs(root):
    root = os.path.abspath(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        if any(f in filenames for f in CORPUS_FILES):
            found.append((dirpath, SELFCHECK in filenames))
    return sorted(found)


def run(root, runner=subprocess.run):
    """Return (ok, skipped, lines)."""
    root = os.path.abspath(root)
    dirs = find_corpus_dirs(root)
    if not dirs:
        return True, True, ["security-corpus: SKIPPED - no ssrf-urls.json / injection-corpus.json in this tree (a skip is not a pass)"]
    lines, ok = [], True
    for dirpath, has_check in dirs:
        rel = safe(os.path.relpath(dirpath, root))
        if not has_check:
            lines.append(f"{rel}: FAIL - corpus file(s) present but {SELFCHECK} is missing")
            ok = False
            continue
        try:
            proc = runner([sys.executable, os.path.join(dirpath, SELFCHECK)], cwd=dirpath,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            lines.append(f"{rel}: FAIL - {SELFCHECK} could not be run to completion")
            ok = False
            continue
        last = safe((proc.stdout or "").strip().splitlines()[-1]) if (proc.stdout or "").strip() else ""
        if proc.returncode == 0:
            lines.append(f"{rel}: PASS - {last}")
        else:
            lines.append(f"{rel}: FAIL - exit code {proc.returncode} - {last}")
            ok = False
    lines.append("security-corpus: PASS" if ok else "security-corpus: FAIL")
    return ok, False, lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) > 1:
        print("usage: ci_corpus_check.py [repository root]", file=sys.stderr)
        return 2
    root = argv[0] if argv else "."
    if not os.path.isdir(root):
        print("error: not a directory", file=sys.stderr)
        return 2
    ok, skipped, lines = run(root)
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("### Security corpus consistency\n" + "\n".join(f"- {l}" for l in lines) + "\n")
    if skipped:
        print("::notice title=security-corpus skipped::no corpus files on this ref - stage SKIPPED, not passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
