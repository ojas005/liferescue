"""KAN-45 step 6 tests: pattern parity between the Python redactor and .gitleaks.toml (T-22).

The real comparison needs the repository's ``.gitleaks.toml`` (or a path in KAN45_GITLEAKS_CONFIG). That file is
not on ``main`` yet (it is a PROPOSED LR 08 draft, owned by the secret-controls PR), so the real-config test is
SKIPPED, loudly, until it exists. The harness itself is tested here against a TOML generated from patterns.json
and against deliberately drifted copies, so a broken harness cannot report a false 'ok'.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from packages.secrets.parity import CORPUS_GENERATORS, load_gitleaks_rules, run_parity
from packages.secrets.redaction import PatternSet

ROOT = Path(__file__).resolve().parents[2]


def real_config_path():
    env = os.environ.get("KAN45_GITLEAKS_CONFIG")
    path = Path(env) if env else ROOT / ".gitleaks.toml"
    return path if path.is_file() else None


def toml_from_patterns(patterns: PatternSet, drop=(), regex_override=None) -> str:
    """A .gitleaks.toml-shaped file mirroring the mapped rules, for harness self-tests."""
    out = ['title = "generated mirror for harness self-test"', "[extend]", "useDefault = true", ""]
    for rule in patterns.rules:
        if not rule.gitleaks_rule or rule.gitleaks_rule in drop:
            continue
        regex = (regex_override or {}).get(rule.gitleaks_rule, rule.regex.pattern)
        assert "'''" not in regex
        out += ["[[rules]]", f"id = '{rule.gitleaks_rule}'", f"regex = '''{regex}'''"]
        if rule.group:
            out.append(f"secretGroup = {rule.group}")
        if rule.allow_match:
            out += ["[[rules.allowlists]]", "regexTarget = 'match'", "regexes = [" + ", ".join(f"'''{a.pattern}'''" for a in rule.allow_match) + "]"]
        out.append("")
    return "\n".join(out)


@unittest.skipIf(sys.version_info < (3, 11), "tomllib needs Python 3.11+")
class HarnessSelfTest(unittest.TestCase):
    def setUp(self):
        self.patterns = PatternSet.load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, text):
        p = Path(self.tmp.name) / "gitleaks.toml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_mirror_toml_roundtrips_and_agrees(self):
        path = self.write(toml_from_patterns(self.patterns))
        rules = load_gitleaks_rules(path)
        mapped = {r.gitleaks_rule for r in self.patterns.rules if r.gitleaks_rule}
        self.assertEqual(set(rules), mapped)
        report = run_parity(path, self.patterns)
        self.assertEqual(report.mismatches, [])
        self.assertEqual(report.problems, [])
        self.assertGreater(report.samples, 100)

    def test_every_mapped_rule_has_a_corpus_generator(self):
        mapped = {r.gitleaks_rule for r in self.patterns.rules if r.gitleaks_rule}
        self.assertEqual(mapped, set(CORPUS_GENERATORS))

    def test_drift_in_a_regex_is_detected(self):
        drifted = toml_from_patterns(self.patterns, regex_override={"liferescue-xai-api-key": r"\bxai-[A-Za-z0-9]{30,}\b"})
        report = run_parity(self.write(drifted), self.patterns)
        self.assertFalse(report.ok)
        self.assertTrue(any("xai" in m for m in report.mismatches), report.mismatches)

    def test_looser_and_tighter_url_rule_is_detected(self):
        loose = toml_from_patterns(self.patterns, regex_override={"liferescue-url-embedded-password": r"""(?i)\b(?:postgres|https?)://[^\s:/@]+:([^\s@]{1,})@[^\s]+"""})
        self.assertFalse(run_parity(self.write(loose), self.patterns).ok)

    def test_rule_missing_on_either_side_is_detected(self):
        missing_in_toml = toml_from_patterns(self.patterns, drop=("liferescue-tavily-api-key",))
        report = run_parity(self.write(missing_in_toml), self.patterns)
        self.assertTrue(any("maps to a gitleaks rule that does not exist" in p for p in report.problems))
        extra = toml_from_patterns(self.patterns) + "\n[[rules]]\nid = 'liferescue-new-provider'\nregex = '''\\bnewp-[a-z]{20,}\\b'''\n"
        report = run_parity(self.write(extra), self.patterns)
        self.assertTrue(any("no redactor pattern: liferescue-new-provider" in p for p in report.problems))

    def test_allowlist_difference_is_detected(self):
        text = toml_from_patterns(self.patterns).replace("regexTarget = 'match'", "regexTarget = 'match'\n# dropped", 1)
        no_allow = text.replace("(password|changeme|example|placeholder|<[^>]+>|\\$\\{[^}]+\\}|\\*+|x{3,})", "(nothing-matches-this)")
        self.assertNotEqual(text, no_allow)
        self.assertFalse(run_parity(self.write(no_allow), self.patterns).ok)

    def test_corpus_is_random_per_run_and_not_committed(self):
        a = CORPUS_GENERATORS["liferescue-xai-api-key"]()
        b = CORPUS_GENERATORS["liferescue-xai-api-key"]()
        self.assertNotEqual(a, b)


@unittest.skipIf(sys.version_info < (3, 11), "tomllib needs Python 3.11+")
class RealConfigParity(unittest.TestCase):
    def test_python_redactor_agrees_with_repository_gitleaks_toml(self):
        path = real_config_path()
        if path is None:
            self.skipTest("SKIPPED: no .gitleaks.toml in the repository (proposed LR 08 draft not merged) and KAN45_GITLEAKS_CONFIG unset")
        report = run_parity(path)
        self.assertEqual(report.mismatches, [], "pattern drift between redactor and scanner")
        self.assertEqual(report.problems, [])
        self.assertGreater(report.samples, 100)


if __name__ == "__main__":
    unittest.main()
