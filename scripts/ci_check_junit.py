#!/usr/bin/env python3
"""Fail-closed reader for a pytest JUnit XML report (used by the per-package CI jobs, KAN-20 follow-up, owner LR 10).

Usage:  python3 scripts/ci_check_junit.py <junit.xml> <minimum number of passed tests>

pytest's own exit code already fails the step on a failing test; this check additionally fails when tests silently
disappear (deleted, deselected, skipped or not collected), which a plain exit code 0 would not reveal.

Exit code: 0 report is sane and passed >= minimum; 1 failures/errors, or fewer passed tests than the minimum;
2 usage error or unreadable/invalid report. Only counts are printed (no test names or messages from the report).
Standard library only. The XML comes from our own pytest run, but is still parsed defensively (DOCTYPE/entities refused).
"""
import sys
import xml.etree.ElementTree as ET


def read_counts(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("DOCTYPE/ENTITY declarations are not accepted")
    root = ET.fromstring(raw)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite")) if root.tag == "testsuites" else None
    if not suites:
        raise ValueError("no <testsuite> element")
    total = failures = errors = skipped = 0
    for s in suites:
        total += int(s.get("tests", "0"))
        failures += int(s.get("failures", "0"))
        errors += int(s.get("errors", "0"))
        skipped += int(s.get("skipped", "0"))
    return total, failures, errors, skipped


def evaluate(total, failures, errors, skipped, minimum):
    passed = total - failures - errors - skipped
    return passed, (failures == 0 and errors == 0 and passed >= minimum)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 2 or not argv[1].isdigit():
        print("usage: ci_check_junit.py <junit.xml> <minimum passed tests>", file=sys.stderr)
        return 2
    try:
        total, failures, errors, skipped = read_counts(argv[0])
    except (OSError, ValueError, ET.ParseError):
        print("error: the JUnit report is missing or invalid", file=sys.stderr)
        return 2
    minimum = int(argv[1])
    passed, ok = evaluate(total, failures, errors, skipped, minimum)
    print(f"tests: {total}, passed: {passed}, failures: {failures}, errors: {errors}, skipped: {skipped}, required passed >= {minimum}")
    print("junit check: PASS" if ok else "junit check: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
