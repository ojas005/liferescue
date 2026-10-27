"""KAN-45 step 1 tests: SecretValue (T-02), SecretRef, request/handle types."""

import copy
import json
import pickle
import unittest
from datetime import timedelta

from packages.secrets.codes import RequestReason
from packages.secrets.errors import InvalidRequest, InvalidSecretRef, SecretWiped
from packages.secrets.secret_types import (
    CredentialRequest,
    Environment,
    Purpose,
    SecretRef,
    SecretValue,
)
from packages.secrets.testing import make_canary


class SecretValueDoesNotLeak(unittest.TestCase):
    """T-02: repr, str, format, f-string, json, pickle, copy of SecretValue reveal nothing."""

    def setUp(self):
        self.canary = make_canary()
        self.value = SecretValue(self.canary)

    def assertNoCanary(self, text):
        self.assertNotIn(self.canary, text)

    def test_repr_str_format_fstring_percent(self):
        outputs = [
            repr(self.value),
            str(self.value),
            format(self.value),
            format(self.value, ">40"),
            f"{self.value}",
            f"{self.value!r}",
            "%s" % self.value,
            "%r" % self.value,
            "{}".format(self.value),
            repr([self.value]),
            repr({"k": self.value}),
            str((self.value,)),
        ]
        for out in outputs:
            self.assertNoCanary(out)
        self.assertEqual(str(self.value), "[REDACTED]")
        self.assertEqual(f"{self.value:>40}", "[REDACTED]")

    def test_json_encoding_is_refused_or_redacted(self):
        with self.assertRaises(TypeError) as ctx:
            json.dumps({"v": self.value})
        self.assertNoCanary(str(ctx.exception))
        self.assertEqual(
            json.loads(json.dumps({"v": self.value}, default=str)), {"v": "[REDACTED]"}
        )

    def test_pickle_all_protocols_refused(self):
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=proto):
                with self.assertRaises(TypeError) as ctx:
                    pickle.dumps(self.value, protocol=proto)
                self.assertNoCanary(str(ctx.exception))

    def test_copy_and_deepcopy_refused(self):
        with self.assertRaises(TypeError):
            copy.copy(self.value)
        with self.assertRaises(TypeError):
            copy.deepcopy(self.value)
        with self.assertRaises(TypeError):
            copy.deepcopy({"nested": [self.value]})

    def test_no_instance_dict_or_bytes_or_len(self):
        self.assertFalse(hasattr(self.value, "__dict__"))
        with self.assertRaises(TypeError):
            bytes(self.value)
        with self.assertRaises(TypeError):
            len(self.value)
        with self.assertRaises(TypeError):
            iter(self.value)

    def test_reveal_is_the_only_exit(self):
        with self.value.reveal() as raw:
            self.assertEqual(raw, self.canary)

    def test_reveal_does_not_swallow_or_decorate_exceptions(self):
        class Boom(Exception):
            pass

        with self.assertRaises(Boom) as ctx:
            with self.value.reveal() as _raw:
                raise Boom("generic")
        self.assertNoCanary(repr(ctx.exception))

    def test_wipe_zeroes_buffer_and_blocks_reveal(self):
        self.value.wipe()
        self.assertTrue(self.value.wiped)
        self.assertEqual(set(self.value._buf), {0})
        with self.assertRaises(SecretWiped) as ctx:
            with self.value.reveal():
                pass
        self.assertNoCanary(str(ctx.exception))

    def test_rejects_empty_or_non_str(self):
        for bad in ("", None, 5, b"bytes"):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    SecretValue(bad)  # type: ignore[arg-type]


class PackageNameSafety(unittest.TestCase):
    def test_stdlib_secrets_module_is_not_shadowed(self):
        import secrets

        self.assertTrue(
            hasattr(secrets, "token_urlsafe"),
            "stdlib 'secrets' is shadowed; run from the repo root",
        )


class SecretRefTests(unittest.TestCase):
    def test_roundtrip(self):
        ref = SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key")
        self.assertEqual(
            ref.to_string(), "secretref://mock/model_inference/mock-model-key"
        )
        self.assertEqual(SecretRef.parse(ref.to_string()), ref)

    def test_unknown_parts_fail_closed_without_echoing_input(self):
        hostile = make_canary("secretref://", 20)
        for text in [
            "secretref://mock/not_a_purpose/x",
            "secretref://prod-ish/model_inference/x",
            "secretref://mock/model_inference",
            "secretref://mock/model_inference/x/y",
            "secretref://mock/model_inference/UPPER",
            "secretref://mock/model_inference/has space",
            "secretref://mock/model_inference/../etc",
            "http://mock/model_inference/x",
            hostile,
            "",
            None,
            "secretref://mock/model_inference/" + "a" * 49,
        ]:
            with self.subTest(
                text=text if text is None or len(str(text)) < 40 else "long"
            ):
                with self.assertRaises(InvalidSecretRef) as ctx:
                    SecretRef.parse(text)
                self.assertNotIn(hostile, str(ctx.exception))

    def test_construct_with_wrong_types_rejected(self):
        with self.assertRaises(InvalidSecretRef):
            SecretRef("mock", Purpose.WEB_SEARCH, "x")  # type: ignore[arg-type]
        with self.assertRaises(InvalidSecretRef):
            SecretRef(Environment.MOCK, "web_search", "x")  # type: ignore[arg-type]

    def test_production_ref_can_be_expressed_so_it_can_be_refused(self):
        ref = SecretRef.parse("secretref://production/db_app/x")
        self.assertIs(ref.environment, Environment.PRODUCTION)


class CredentialRequestTests(unittest.TestCase):
    ref = SecretRef(Environment.MOCK, Purpose.WEB_SEARCH, "mock-search-key")

    def make(self, **kw):
        base = dict(
            task_id="T-1",
            run_id="R-1",
            agent_id="LR-06",
            ref=self.ref,
            reason_code=RequestReason.WEB_SEARCH_CALL,
        )
        base.update(kw)
        return CredentialRequest(**base)

    def test_valid(self):
        req = self.make(requested_ttl=timedelta(minutes=5))
        self.assertEqual(req.agent_id, "LR-06")

    def test_invalid_ids_and_codes_rejected_without_echo(self):
        secretish = make_canary("x ", 16)  # contains a space: invalid id shape
        for kw in [
            dict(task_id=secretish),
            dict(run_id=""),
            dict(agent_id="LR 06"),
            dict(agent_id="a" * 65),
            dict(task_id=None),
            dict(reason_code="model_call"),
            dict(ref="secretref://mock/web_search/x"),
            dict(requested_ttl=15),
            dict(correlation_id="bad id"),
        ]:
            with self.subTest(kw=list(kw)):
                with self.assertRaises(InvalidRequest) as ctx:
                    self.make(**kw)
                self.assertNotIn(secretish, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
