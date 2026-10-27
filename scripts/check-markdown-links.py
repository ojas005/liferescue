#!/usr/bin/env python3
"""Check that relative links in Markdown files resolve to existing files.

External (http/https/mailto) links and pure anchors are NOT checked (no network use).
Fenced code blocks and inline code spans are skipped.
Exit code 1 if any relative link target is missing.
"""

import os
import re
import sys

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", ".terraform"}


def md_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".md"):
                yield os.path.join(dirpath, name)


def strip_code(text):
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    bad = []
    count = 0
    for path in md_files(root):
        with open(path, encoding="utf-8") as fh:
            text = strip_code(fh.read())
        for target in LINK.findall(text):
            if re.match(r"^(https?:|mailto:|#)", target):
                continue
            count += 1
            rel = target.split("#", 1)[0]
            if not rel:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), rel))
            if not os.path.exists(resolved):
                bad.append(f"{path}: broken relative link -> {target}")
    for line in bad:
        print(line)
    print(f"Checked {count} relative links; {len(bad)} broken")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
