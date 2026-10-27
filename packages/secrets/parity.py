"""Pattern parity harness (KAN-45 spec T-22, step 6).

Compares the Python redactor's patterns (``patterns.json``) with the custom rules in ``.gitleaks.toml``
on a corpus of positive and negative samples GENERATED AT RUNTIME (random characters; nothing realistic
is committed). Any disagreement, and any rule that exists on only one side, is reported so the build can fail.

Caveats (stated, not hidden):
  * gitleaks uses Go RE2, this harness uses Python ``re``. The current rules use only syntax with the same
    meaning in both, but identical behaviour is NOT assumed in general: the corpus is the evidence.
  * Only the custom ``[[rules]]`` of the TOML are compared. gitleaks default rules (``useDefault = true``),
    ``keywords`` prefiltering and entropy are not modelled.
  * The harness needs ``tomllib`` (Python 3.11+).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .redaction import PatternSet
from .testing import random_chars

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


@dataclass
class GitleaksRule:
    rule_id: str
    regex: "re.Pattern[str]"
    secret_group: int
    allow_match: tuple


@dataclass
class ParityReport:
    mismatches: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    samples: int = 0

    @property
    def ok(self) -> bool:
        return not self.mismatches and not self.problems


def load_gitleaks_rules(path: Path) -> Dict[str, GitleaksRule]:
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("tomllib (Python 3.11+) is required for the parity harness")
    with open(path, "rb") as fh:
        doc = tomllib.load(fh)
    rules: Dict[str, GitleaksRule] = {}
    for item in doc.get("rules", []):
        allow = []
        for al in item.get("allowlists", []):
            if al.get("regexTarget", "secret") == "match":
                allow.extend(re.compile(r) for r in al.get("regexes", []))
        rules[item["id"]] = GitleaksRule(
            item["id"],
            re.compile(item["regex"]),
            int(item.get("secretGroup", 0)),
            tuple(allow),
        )
    return rules


def _gitleaks_secret(rule: GitleaksRule, sample: str) -> Optional[str]:
    for m in rule.regex.finditer(sample):
        if any(a.search(m.group(0)) for a in rule.allow_match):
            continue
        return m.group(rule.secret_group)
    return None


def _python_secret(patterns: PatternSet, rule_id: str, sample: str) -> Optional[str]:
    for rule in patterns.rules:
        if rule.gitleaks_rule != rule_id:
            continue
        for m in rule.regex.finditer(sample):
            if any(a.search(m.group(0)) for a in rule.allow_match):
                continue
            return m.group(rule.group)
    return None


# -------------------------------------------------------------------------------- corpus -------
def _ctx(secret: str) -> List[str]:
    return [
        secret,
        f"key = {secret}",
        f'"{secret}"',
        f"prefix text {secret} suffix text",
        f"line one\n{secret}\nline three",
    ]


def _gen_xai() -> tuple:
    pos = [c for n in (40, 41, 55, 80) for c in _ctx("xai-" + random_chars(n))]
    neg = [
        "xai-" + random_chars(39),
        "XAI-" + random_chars(50),
        "a" + "xai-" + random_chars(50),
        "xa1-" + random_chars(50),
        "xai" + random_chars(50),
    ]
    return pos, neg


def _gen_nvidia() -> tuple:
    mixed = lambda n: "".join(random_chars(1) if i % 7 else "-" for i in range(n))
    pos = [
        c
        for s in (
            "nvapi-" + random_chars(40),
            "nvapi-" + mixed(52),
            "nvapi-" + random_chars(60) + "_",
        )
        for c in _ctx(s)
    ]
    neg = [
        "nvapi-" + random_chars(39),
        "nvapi_" + random_chars(50),
        "NVAPI-" + random_chars(50),
        "x" + "nvapi-" + random_chars(50),
    ]
    return pos, neg


def _gen_tavily() -> tuple:
    pos = [c for n in (20, 28, 45) for c in _ctx("tvly-" + random_chars(n))]
    neg = [
        "tvly-" + random_chars(19),
        "tvly" + random_chars(30),
        "TVLY-" + random_chars(30),
        "q" + "tvly-" + random_chars(30),
    ]
    return pos, neg


def _gen_atlassian() -> tuple:
    pos = [
        c
        for s in (
            "ATATT3" + random_chars(50),
            "ATATT3" + random_chars(70) + "=",
            "ATATT3" + random_chars(25) + "-_" + random_chars(30),
        )
        for c in _ctx(s)
    ]
    neg = [
        "ATATT3" + random_chars(49),
        "atatt3" + random_chars(60),
        "ATATT2" + random_chars(60),
        "Z" + "ATATT3" + random_chars(60),
    ]
    return pos, neg


def _gen_nebius() -> tuple:
    pos = []
    for name in (
        "NEBIUS_API_KEY",
        "nebius-token",
        "Nebius_Secret",
        "NEBIUS_SERVICE_ACCOUNT_KEY",
        "nebiusapikey",
    ):
        v = random_chars(24) + "-_.=+/"[: len(name) % 6]
        pos += [f"{name}={v}", f'{name}: "{v}"', f"export {name}='{v}'"]
    neg = [
        f"NEBIUS_API_KEY={random_chars(19)}",
        f"NEBIUS_REGION={random_chars(30)}",
        "the nebius api key is stored elsewhere",
        f"OTHER_API_KEY={random_chars(30)}",
    ]
    return pos, neg


def _gen_url() -> tuple:
    pos = []
    for scheme in (
        "postgres",
        "postgresql",
        "redis",
        "rediss",
        "amqp",
        "amqps",
        "mongodb",
        "mongodb+srv",
        "mysql",
        "https",
        "http",
    ):
        pw = random_chars(12)
        pos.append(f"{scheme}://svc:{pw}@db.example.invalid:5432/app")
    short_pw, long_pw = random_chars(6), random_chars(20)
    # URLs are assembled from parts so that no source line itself looks like a URL with an embedded password
    pos += [
        "line\nrediss://u:" + short_pw + "@h/0\nline",
        "x = 'https://user:" + long_pw + "@host.example.invalid/path'",
    ]
    neg = [
        "postgres://user:changeme@localhost/db",
        "redis://u:${REDIS_PASSWORD}@h/0",
        "https://u:<password>@h/",
        "http://u:example@h/",
        "http://u:xxxx@h/",
        "http://u:****@h/",
        "postgres://user:pw@h/db",
        "postgres://localhost:5432/db",
        "ftp://u:" + random_chars(12) + "@h/",
        "https://example.invalid/a:b@c",
    ]
    return pos, neg


def _gen_private_key() -> tuple:
    begin = "-----BEGIN "  # assembled at runtime: no complete PEM header is committed
    pos = [f"{begin}{kind}PRIVATE KEY-----" for kind in ("", "RSA ", "EC ", "OPENSSH ")]
    pos += [
        f"text\n{begin}{kind}PRIVATE KEY-----\n{random_chars(64)}\n"
        for kind in ("", "RSA ")
    ]
    neg = [
        "-----BEGIN PUBLIC KEY-----",
        "-----BEGIN CERTIFICATE-----",
        "-----BEGIN " + "DSA PRIVATE KEY-----",
        "BEGIN PRIVATE KEY",
        "-----BEGIN-----PRIVATE KEY",
    ]
    return pos, neg


CORPUS_GENERATORS: Dict[str, Callable[[], tuple]] = dict(
    [
        ("liferescue-xai-api-key", _gen_xai),
        ("liferescue-nvidia-api-key", _gen_nvidia),
        ("liferescue-tavily-api-key", _gen_tavily),
        ("liferescue-atlassian-api-token", _gen_atlassian),
        ("liferescue-nebius-credential-assignment", _gen_nebius),
        ("liferescue-url-embedded-password", _gen_url),
        ("liferescue-github-app-private-key-file-ref", _gen_private_key),
    ]
)


def run_parity(toml_path: Path, patterns: Optional[PatternSet] = None) -> ParityReport:
    patterns = patterns if patterns is not None else PatternSet.load()
    gl = load_gitleaks_rules(toml_path)
    report = ParityReport()
    mapped = {r.gitleaks_rule for r in patterns.rules if r.gitleaks_rule}
    for rid in sorted(set(gl) - mapped):
        report.problems.append(f"gitleaks rule has no redactor pattern: {rid}")
    for rid in sorted(mapped - set(gl)):
        report.problems.append(
            f"redactor pattern maps to a gitleaks rule that does not exist: {rid}"
        )
    for rid in sorted(set(gl) & mapped):
        gen = CORPUS_GENERATORS.get(rid)
        if gen is None:
            report.problems.append(f"no corpus generator for rule: {rid}")
            continue
        positives, negatives = gen()
        for kind, samples in (("positive", positives), ("negative", negatives)):
            for sample in samples:
                report.samples += 1
                g, p = (
                    _gitleaks_secret(gl[rid], sample),
                    _python_secret(patterns, rid, sample),
                )
                if (g is None) != (p is None):
                    report.mismatches.append(
                        f"{rid} [{kind}]: gitleaks={'match' if g is not None else 'no match'} python={'match' if p is not None else 'no match'}"
                    )
                elif g is not None and gl[rid].secret_group > 0 and g != p:
                    # captured secret text is compared only for rules with a secretGroup; for whole-match rules the
                    # redactor may deliberately cover MORE than gitleaks reports (e.g. a whole PEM body vs its header)
                    report.mismatches.append(
                        f"{rid} [{kind}]: matched different text for the secret group"
                    )
                elif kind == "positive" and g is None:
                    report.mismatches.append(
                        f"{rid}: corpus positive matched on neither side (corpus bug)"
                    )
                elif kind == "negative" and g is not None:
                    report.mismatches.append(
                        f"{rid}: corpus negative matched on both sides (corpus bug)"
                    )
    return report
