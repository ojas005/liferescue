"""KAN-45 test T-26 and spec 8.1: the slice's own files contain no value and no complete realistic credential.

This is a self-scan with the redactor's patterns (the same source the scanner-parity test compares with
.gitleaks.toml). It complements, and does not replace, the CI secret scan owned by LR 10.
"""
import json
import re
import unittest
from pathlib import Path

from packages.secrets.policy import DEFAULT_POLICY_PATH, load_policy
from packages.secrets.redaction import PatternSet, Redactor

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ("packages/secrets", "tests/security", "docs/security")
SKIP = {"__pycache__"}


def files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not (SKIP & set(path.parts)) and path.suffix in {".py", ".md", ".json", ".txt", ".toml"}:
                yield path


class SelfScan(unittest.TestCase):
    def test_no_committed_file_matches_a_secret_pattern(self):
        # Only the scanner-mirrored rules: the Python-only runtime extras (assignment, cookie, ...) are deliberately
        # broad and would flag ordinary test code such as {"password": canary}.
        redactor = Redactor(patterns=PatternSet.load().scanner_mirrored())
        scanned = 0
        for path in files():
            text = path.read_text(encoding="utf-8")
            scanned += 1
            self.assertEqual(redactor.find_leaks(text), (), f"secret-shaped content in {path.relative_to(ROOT)}")
        self.assertGreater(scanned, 25)

    def test_policy_file_contains_names_and_limits_only_T26(self):
        redactor = Redactor(patterns=PatternSet.load())  # all rules, including the broad ones
        text = DEFAULT_POLICY_PATH.read_text(encoding="utf-8")
        self.assertEqual(redactor.find_leaks(text), ())
        policy = load_policy()
        self.assertTrue(policy.grants)
        doc = json.loads(text)
        allowed = {"agent_id", "purpose", "names", "environments", "max_ttl_seconds"}
        for grant in doc["grants"]:
            self.assertLessEqual(set(grant), allowed)
            for name in grant["names"]:
                self.assertTrue(name.startswith("mock-"), name)
                self.assertLess(len(name), 30)

    def test_no_file_holds_a_complete_private_key_header(self):
        for path in files():
            text = path.read_text(encoding="utf-8")
            found = re.search(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----", text) is not None
            self.assertFalse(found, f"complete PEM header in {path.relative_to(ROOT)}")

    def test_self_scan_would_catch_a_planted_value(self):
        from packages.secrets.testing import random_chars

        redactor = Redactor(patterns=PatternSet.load().scanner_mirrored())
        self.assertEqual(redactor.find_leaks("note: xai-" + random_chars(44)), ("xai_key",))


if __name__ == "__main__":
    unittest.main()
