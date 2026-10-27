"""KAN-45 step 5 tests: redaction library (T-16, T-17) and pattern redaction."""

import base64
import json
import unittest

from fixtures_broker import MODEL_REF, Rig
from packages.secrets.redaction import (
    DENIED_KEY_TERMS,
    KnownValueMatcher,
    PatternSet,
    Redactor,
    base64_variants,
    marker,
)
from packages.secrets.secret_types import SecretValue
from packages.secrets.testing import make_canary, random_chars
from scenarios import emit_through_sinks, leaks_in


class KnownValueRedaction(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.rig.request()  # leases MODEL_REF: its canary joins the known set
        self.canary = self.rig.canaries[MODEL_REF]
        self.r = self.rig.broker.redactor

    def test_exact_value_is_replaced_with_marker_and_nothing_else_of_it_survives(self):
        text = f"before {self.canary} after"
        out = self.r.redact_text(text)
        self.assertEqual(out, f"before {marker('secret')} after")
        self.assertNotIn(self.canary, out)
        # no partial reveal: no prefix/suffix/length of the secret appears
        self.assertNotIn(self.canary[:12], out.replace("mock-", ""))

    def test_T16_every_sink_and_encoding_is_clean(self):
        outputs = emit_through_sinks(self.rig, self.canary)
        self.assertGreaterEqual(len(outputs), 20)
        for name, text in outputs.items():
            with self.subTest(scenario=name):
                self.assertEqual(leaks_in(text, self.canary), [], f"{name} leaked")
                self.assertIn(
                    "[REDACTED:", text, f"{name}: a redaction marker must be present"
                )

    def test_T16_second_independent_canary_and_two_at_once(self):
        other = self.rig.seed(
            MODEL_REF.__class__(
                MODEL_REF.environment,
                MODEL_REF.purpose.__class__.WEB_SEARCH,
                "mock-search-key",
            )
        )
        self.rig.request(
            MODEL_REF.__class__(
                MODEL_REF.environment,
                MODEL_REF.purpose.__class__.WEB_SEARCH,
                "mock-search-key",
            )
        )
        text = f"a={self.canary} b={other}"
        out = self.r.redact_text(text)
        self.assertEqual(leaks_in(out, self.canary), [])
        self.assertEqual(leaks_in(out, other), [])

    def test_base64_in_all_three_alignments_embedded_in_larger_data(self):
        for prefix_len in range(0, 6):
            for suffix_len in range(0, 4):
                blob = (
                    random_chars(prefix_len).encode()
                    + self.canary.encode()
                    + random_chars(suffix_len).encode()
                )
                for enc in (
                    base64.b64encode(blob),
                    base64.urlsafe_b64encode(blob),
                    base64.b64encode(blob).rstrip(b"="),
                ):
                    with self.subTest(prefix=prefix_len, suffix=suffix_len):
                        out = self.r.redact_text(enc.decode())
                        self.assertIn("[REDACTED:secret]", out)

    def test_base64_variants_are_substrings_of_real_encodings(self):
        data = self.canary.encode()
        variants = base64_variants(data)
        self.assertGreaterEqual(len(variants), 3)
        for v in variants:
            self.assertGreaterEqual(len(v), 8)

    def test_split_forms(self):
        c = self.canary
        for text in (
            f"{c[:5]} {c[5:]}",
            f"{c[:7]}\n{c[7:15]}\r\n   {c[15:]}",
            f'"{c[:6]}"+"{c[6:]}"',
            "\\\n".join([c[:10], c[10:]]),
        ):
            with self.subTest(text=text.replace(c[0:3], "<s>")[:20]):
                self.assertEqual(leaks_in(self.r.redact_text(text), c), [])
                self.assertNotIn(c[8:18], self.r.redact_text(text))

    def test_value_that_is_not_leased_is_not_touched_by_known_value_logic(self):
        text = "plain text without secrets " + random_chars(40)
        self.assertEqual(
            Redactor(
                self.rig.broker.leased_values, patterns=PatternSet(())
            ).redact_text(text),
            text,
        )

    def test_known_set_tracks_live_leases_only(self):
        """Documented limitation (spec 6.2: 'currently leased values'): once a lease is revoked its
        value is dropped from memory and from the known set; the pattern layer still applies."""
        from packages.secrets.codes import RevokeReason

        self.rig.broker.revoke_task("T-1", reason_code=RevokeReason.TASK_END)
        self.assertEqual(self.r.redact_text(self.canary), self.canary)

    def test_short_values_only_exact_match_to_avoid_destroying_text(self):
        r = Redactor(patterns=PatternSet(()), extra_values=["abc12"])
        self.assertEqual(r.redact_text("x abc12 y"), "x [REDACTED:secret] y")
        self.assertEqual(r.redact_text("x a b c 1 2 y"), "x a b c 1 2 y")

    def test_secretvalue_in_text_context_is_already_safe(self):
        self.assertEqual(
            self.r.redact_text(f"{SecretValue(self.canary)}"), "[REDACTED]"
        )

    def test_matcher_handles_many_values_and_regex_metacharacters(self):
        values = [make_canary("mock-", 20) + "+.*?[](){}|^$\\" for _ in range(30)]
        KnownValueMatcher(values)
        text = " ".join(f"v={v}" for v in values)
        r = Redactor(patterns=PatternSet(()), extra_values=values)
        out = r.redact_text(text)
        for v in values:
            self.assertNotIn(v[:25], out)

    def test_redaction_counters_by_kind_and_sink_without_content(self):
        before = self.rig.broker.metrics.snapshot()
        self.r.redact_text(f"k={self.canary}", sink="log")
        after = self.rig.broker.metrics.snapshot()
        key = "redactions{secret:log}"
        self.assertEqual(after.get(key, 0), before.get(key, 0) + 1)
        self.assertNotIn(self.canary, repr(after))

    def test_oversize_text_fails_closed(self):
        out = self.r.redact_text("a" * 5_000_001)
        self.assertEqual(out, "[REDACTED:oversize]")
        self.assertEqual(self.r.find_leaks("a" * 5_000_001), ("oversize",))


class PatternRedaction(unittest.TestCase):
    def setUp(self):
        self.r = Redactor(patterns=PatternSet.load())

    def check(self, text, kind, secret):
        out = self.r.redact_text(text)
        self.assertIn(f"[REDACTED:{kind}]", out)
        self.assertNotIn(secret, out)
        self.assertEqual(self.r.find_leaks(text), (kind,))

    def test_provider_key_shapes_generated_at_runtime(self):
        for prefix, n, kind in [
            ("xai-", 44, "xai_key"),
            ("nvapi-", 56, "nvidia_key"),
            ("tvly-", 30, "tavily_key"),
            ("ATATT3", 70, "atlassian_token"),
        ]:
            with self.subTest(kind=kind):
                secret = prefix + random_chars(n)
                self.check(f"my key is {secret}.", kind, secret)

    def test_assignment_and_url_forms(self):
        secret = random_chars(32)
        self.check(f"NEBIUS_API_KEY={secret}", "nebius_credential", secret)
        pw = random_chars(20)
        out = self.r.redact_text(f"postgres://svc:{pw}@db.example.invalid:5432/app")
        self.assertEqual(
            out,
            "postgres://svc:"
            + "[REDACTED:url_password]"
            + "@db.example.invalid:5432/app",
        )

    def test_placeholder_url_passwords_are_not_redacted(self):
        for text in (
            "postgres://user:changeme@localhost/db",
            "redis://u:${REDIS_PASSWORD}@h/0",
            "https://u:<password>@h/",
        ):
            self.assertEqual(self.r.redact_text(text), text)

    def test_private_key_block_whole_body_removed(self):
        header, footer = (
            "-----BEGIN " + "PRIVATE KEY-----",
            "-----END " + "PRIVATE KEY-----",
        )
        body = "\n".join(random_chars(64) for _ in range(3))
        out = self.r.redact_text(f"before\n{header}\n{body}\n{footer}\nafter")
        self.assertEqual(out, "before\n[REDACTED:private_key]\nafter")
        unterminated = self.r.redact_text(f"x {header}\n{body}")
        self.assertNotIn(body.splitlines()[0], unterminated)
        other = "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"
        self.assertIn(
            "[REDACTED:private_key]",
            self.r.redact_text(f"{other}\n{body}\n-----END ENCRYPTED PRIVATE KEY-----"),
        )

    def test_headers_and_query_params(self):
        tok = random_chars(30)
        for text, kind in [
            (f"Authorization: Bearer {tok}", "bearer_token"),
            (f"authorization={tok}", "auth_header"),
            (f"Cookie: session={tok}; theme=dark", "cookie"),
            (f"Set-Cookie: sid={tok}; HttpOnly", "cookie"),
            (f"https://x.example.invalid/cb?code=1&api_key={tok}&z=1", "url_param"),
            (f'{{"password": "{tok}"}}', "assignment"),
            (f"client_secret: {tok}", "assignment"),
        ]:
            with self.subTest(text=text[:25]):
                out = self.r.redact_text(text)
                self.assertNotIn(tok, out)
                self.assertIn("[REDACTED:", out)

    def test_ordinary_text_is_untouched(self):
        for text in [
            "The quick brown fox",
            "see tokens per minute: 30",
            "max_tokens=4096",
            "use xai- prefix docs",
            "bearer of bad news",
            "Authorization is required",
            "password policy: min length 12",
            "https://example.invalid/path?page=2&sort=asc",
            "token_count: 17",
            "secretref://mock/model_inference/mock-model-key",
        ]:
            with self.subTest(text=text):
                self.assertEqual(self.r.redact_text(text), text)

    def test_overlapping_matches_merge_into_one_marker(self):
        tok = random_chars(30)
        out = self.r.redact_text(f"Authorization: Bearer {tok}")
        self.assertEqual(out.count("[REDACTED:"), 1)

    def test_pattern_file_validation_fails_closed(self):
        from packages.secrets.errors import ConfigurationError

        for bad in [
            [],
            {"version": 2, "rules": []},
            {"version": 1, "rules": "x"},
            {
                "version": 1,
                "rules": [{"id": "a", "kind": "k", "regex": "(", "group": 0}],
            },
            {
                "version": 1,
                "rules": [{"id": "a", "kind": "k", "regex": "a", "group": 3}],
            },
            {
                "version": 1,
                "rules": [{"id": "a", "kind": "BAD KIND", "regex": "a", "group": 0}],
            },
            {
                "version": 1,
                "rules": [
                    {"id": "a", "kind": "k", "regex": "a", "group": 0},
                    {"id": "a", "kind": "k", "regex": "b", "group": 0},
                ],
            },
        ]:
            with self.subTest(bad=str(bad)[:40]):
                with self.assertRaises(ConfigurationError):
                    PatternSet.from_mapping(bad)

    def test_pattern_file_has_no_whole_provider_key(self):
        from packages.secrets.redaction import PATTERNS_PATH

        text = PATTERNS_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"\bxai-[A-Za-z0-9]{40,}")
        self.assertNotRegex(text, r"\bnvapi-[A-Za-z0-9_\-]{40,}")


class KeyNameRule(unittest.TestCase):
    """T-17: values under denied keys are redacted regardless of content."""

    def setUp(self):
        self.r = Redactor(patterns=PatternSet(()))

    def test_every_denied_term_in_many_spellings_and_value_types(self):
        for term in DENIED_KEY_TERMS:
            for spelling in {
                term,
                term.upper(),
                term.title(),
                term.replace("_", "-"),
                "x-" + term.replace("_", "-"),
                "my_" + term,
                term.replace("_", " "),
            }:
                for value in (
                    "hello",
                    "short",
                    12345,
                    {"nested": "ok"},
                    ["a", "b"],
                    True,
                    "",
                    None,
                ):
                    with self.subTest(key=spelling, value=repr(value)[:10]):
                        out = self.r.redact({spelling: value})
                        self.assertEqual(out, {spelling: "[REDACTED:field]"})

    def test_camel_case_and_nested_and_lists(self):
        out = self.r.redact(
            {
                "dbPassword": "x",
                "items": [{"apiKey": "k1", "name": "n"}],
                "deep": {"a": {"Authorization": "Bearer q"}},
            }
        )
        self.assertEqual(out["dbPassword"], "[REDACTED:field]")
        self.assertEqual(out["items"], [{"apiKey": "[REDACTED:field]", "name": "n"}])
        self.assertEqual(out["deep"]["a"]["Authorization"], "[REDACTED:field]")

    def test_other_keys_keep_values(self):
        data = {"name": "alice", "count": 3, "ok": True, "items": [1, 2], "when": None}
        self.assertEqual(self.r.redact(data), data)

    def test_overredaction_is_documented_and_exemption_is_explicit(self):
        self.assertEqual(
            self.r.redact({"max_tokens": 4096}), {"max_tokens": "[REDACTED:field]"}
        )
        exempt = Redactor(patterns=PatternSet(()), key_exempt=["max_tokens"])
        self.assertEqual(
            exempt.redact({"max_tokens": 4096, "token": "t"}),
            {"max_tokens": 4096, "token": "[REDACTED:field]"},
        )

    def test_canary_in_key_names_and_values_of_other_keys(self):
        r = Redactor(patterns=PatternSet(()), extra_values=["mock-" + random_chars(24)])
        secret = r._extra[0]
        out = r.redact(
            {secret: "v", "note": f"see {secret}", "list": [secret], "tup": (secret,)}
        )
        self.assertNotIn(secret, json.dumps(out))

    def test_unknown_objects_cycles_and_depth_fail_closed(self):
        class Opaque:
            def __repr__(self):
                return "opaque-" + "z" * 5

        self.assertEqual(self.r.redact({"o": Opaque()}), {"o": "[REDACTED:object]"})
        cyc: dict = {}
        cyc["self"] = cyc
        self.assertEqual(self.r.redact(cyc), {"self": "[REDACTED:cycle]"})
        deep: list = []
        node = deep
        for _ in range(40):
            nxt: list = []
            node.append(nxt)
            node = nxt
        self.assertIn("[REDACTED:depth]", json.dumps(self.r.redact(deep)))

    def test_safe_scalars_pass_and_secretvalue_is_marked(self):
        import datetime
        import uuid
        import decimal
        import enum

        class Color(enum.Enum):
            RED = "red"

        data = {
            "when": datetime.datetime(2026, 1, 1),
            "id": uuid.UUID(int=5),
            "d": decimal.Decimal("1.5"),
            "c": Color.RED,
        }
        out = self.r.redact(data)
        self.assertEqual(out["c"], "red")
        self.assertEqual(out["id"], str(uuid.UUID(int=5)))
        self.assertEqual(
            self.r.redact([SecretValue("abcdefgh")]), ["[REDACTED:secret]"]
        )


class ExceptionRedaction(unittest.TestCase):
    def test_chain_and_traceback_text_redacted(self):
        secret = "mock-" + random_chars(30)
        r = Redactor(patterns=PatternSet(()), extra_values=[secret])
        try:
            try:
                raise ValueError(f"a {secret}")
            except ValueError as inner:
                raise RuntimeError(f"b {secret}") from inner
        except RuntimeError as exc:
            text = r.redact_exception(exc)
            tb = r.format_traceback(exc)
        for t in (text, tb):
            self.assertNotIn(secret, t)
            self.assertIn("[REDACTED:secret]", t)
        self.assertIn("RuntimeError", text)
        self.assertIn("ValueError", text)

    def test_exception_with_weird_args_does_not_break_redaction(self):
        class BadStr:
            def __str__(self):
                raise RuntimeError("no str")

        r = Redactor(patterns=PatternSet(()))
        self.assertIn("Exception", r.redact_exception(Exception(BadStr())))


if __name__ == "__main__":
    unittest.main()
