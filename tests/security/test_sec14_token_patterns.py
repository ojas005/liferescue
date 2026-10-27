"""LR 08 SEC-14 (Low): GitHub (ghp_/github_pat_) and sk- tokens are redacted (stdlib only: runs in python-unit-tests)."""

import unittest

from packages.secrets.redaction import PatternSet, Redactor

GHP = "ghp_" + "A1b2C3d4E5" * 4  # synthetic
PAT = "github_pat_" + "11ABCDEFG0" * 3 + "_xyz"  # synthetic
SK = "sk-" + "Zz9Yy8Xx7W" * 3  # synthetic


class TestSec14(unittest.TestCase):
    def test_redactor(self):
        r = Redactor(patterns=PatternSet.load())
        for tok, kind in ((GHP, "github_token"), (PAT, "github_token"), (SK, "sk_key")):
            with self.subTest(kind=kind):
                out = r.redact_text(f"leaked {tok} here", sink="log")
                self.assertNotIn(tok, out)
                self.assertIn(f"[REDACTED:{kind}]", out)
        self.assertEqual(
            r.redact_text("task-sketch skill", sink="log"), "task-sketch skill"
        )


if __name__ == "__main__":
    unittest.main()
