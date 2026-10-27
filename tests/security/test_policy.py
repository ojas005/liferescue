"""KAN-45 step 2 tests: policy loader (T-03/T-04 policy side, T-14 policy side, T-26 policy side)."""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from packages.secrets.errors import PolicyError
from packages.secrets.policy import (
    DEFAULT_POLICY_PATH,
    Grant,
    Policy,
    load_policy,
    parse_policy,
    policy_from_mapping,
)
from packages.secrets.secret_types import Environment, Purpose, SecretRef
from packages.secrets.testing import make_canary


def grant(**over):
    base = {
        "agent_id": "LR-06",
        "purpose": "model_inference",
        "names": ["mock-model-key"],
        "environments": ["mock"],
        "max_ttl_seconds": 600,
    }
    base.update(over)
    return base


def doc(*grants, version=1):
    return {"version": version, "grants": list(grants)}


class PackagedPolicy(unittest.TestCase):
    def test_packaged_policy_loads_and_is_mock_only(self):
        policy = load_policy()
        self.assertTrue(policy.grants)
        for g in policy.grants:
            self.assertEqual(g.environments, frozenset({Environment.MOCK}))
            self.assertTrue(all(n.startswith("mock-") for n in g.names))

    def test_default_deny(self):
        policy = load_policy()
        ref = SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key")
        self.assertIsNotNone(policy.find_grant("LR-06", ref))
        self.assertIsNone(policy.find_grant("LR-05", ref), "unknown agent")
        self.assertIsNone(policy.find_grant("LR-04", ref), "wrong purpose for agent")
        other = SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-other-key")
        self.assertIsNone(policy.find_grant("LR-06", other), "unlisted name")
        test_env = SecretRef(
            Environment.TEST, Purpose.MODEL_INFERENCE, "mock-model-key"
        )
        self.assertIsNone(
            policy.find_grant("LR-06", test_env), "environment not granted"
        )
        prod = SecretRef(
            Environment.PRODUCTION, Purpose.MODEL_INFERENCE, "mock-model-key"
        )
        self.assertIsNone(policy.find_grant("LR-06", prod))

    def test_empty_policy_denies_everything(self):
        self.assertIsNone(
            Policy().find_grant(
                "LR-06",
                SecretRef(Environment.MOCK, Purpose.WEB_SEARCH, "mock-search-key"),
            )
        )


class PolicyValidation(unittest.TestCase):
    def test_valid_roundtrip_values(self):
        policy = policy_from_mapping(doc(grant()))
        self.assertEqual(policy.grants[0].max_ttl, timedelta(seconds=600))
        self.assertIsInstance(policy.grants[0], Grant)

    def test_production_grant_rejected_T14(self):
        with self.assertRaises(PolicyError):
            policy_from_mapping(doc(grant(environments=["production"])))
        with self.assertRaises(PolicyError):
            policy_from_mapping(doc(grant(environments=["mock", "production"])))

    def test_invalid_shapes_fail_closed(self):
        bad_docs = [
            [],
            {},
            {"version": 2, "grants": []},
            {"version": True, "grants": []},
            {"version": 1},
            {"version": 1, "grants": {}},
            {"version": 1, "grants": [], "extra": 1},
            doc(grant(purpose="unknown_purpose")),
            doc(grant(environments=["staging"])),
            doc(grant(environments=[])),
            doc(grant(names=[])),
            doc(grant(names="mock-model-key")),
            doc(grant(names=["UPPER"])),
            doc(grant(names=["has space"])),
            doc(grant(agent_id="LR 06")),
            doc(grant(max_ttl_seconds=0)),
            doc(grant(max_ttl_seconds=-5)),
            doc(grant(max_ttl_seconds="900")),
            doc(grant(max_ttl_seconds=True)),
            doc(grant(max_ttl_seconds=10**9)),
            doc(grant(unexpected="x")),
            doc(grant(), grant(names=["mock-other-key"])),  # duplicate (agent, purpose)
            doc("not-a-mapping"),
        ]
        for i, bad in enumerate(bad_docs):
            with self.subTest(case=i), self.assertRaises(PolicyError):
                policy_from_mapping(bad)

    def test_invalid_json_and_duplicates_and_size(self):
        for text in ["", "{", "[]", '{"version":1,"version":1,"grants":[]}', "\xff"]:
            with self.subTest(text=text), self.assertRaises(PolicyError):
                parse_policy(text)
        with self.assertRaises(PolicyError):
            parse_policy(b"\xff\xfe\x00")
        with self.assertRaises(PolicyError):
            parse_policy(b" " * (64 * 1024 + 1))
        with self.assertRaises(PolicyError):
            parse_policy(12345)  # type: ignore[arg-type]

    def test_missing_file_fails_closed(self):
        with self.assertRaises(PolicyError):
            load_policy(Path(tempfile.gettempdir()) / "no-such-policy-kan45.json")

    def test_error_messages_never_echo_file_content_T26(self):
        canary = make_canary("mock-", 40)
        hostile = [
            doc(grant(names=[canary])),  # value-shaped name
            doc(grant(agent_id=canary + " x")),
            doc(grant(purpose=canary)),
            doc(grant(environments=[canary])),
            {"version": 1, "grants": [], canary: 1},
            {"version": canary, "grants": []},
        ]
        for i, bad in enumerate(hostile):
            with self.subTest(case=i):
                with self.assertRaises(PolicyError) as ctx:
                    parse_policy(json.dumps(bad))
                self.assertNotIn(canary, str(ctx.exception))
                self.assertNotIn(canary, repr(ctx.exception.args))
                self.assertIsNone(ctx.exception.__cause__)
                self.assertIsNone(ctx.exception.__context__)

    def test_value_shaped_names_rejected_T26(self):
        for name in [
            "mock-" + "a1b2c3d4e5f6g7h8i9j0",  # one long segment
            "k1-2345-6789-0123",  # too many digits
        ]:
            with self.subTest(name=name), self.assertRaises(PolicyError):
                policy_from_mapping(doc(grant(names=[name])))

    def test_packaged_policy_file_has_no_unexpected_content(self):
        text = DEFAULT_POLICY_PATH.read_text(encoding="utf-8")
        parsed = json.loads(text)
        self.assertEqual(set(parsed), {"version", "grants"})
        for g in parsed["grants"]:
            self.assertLessEqual(
                set(g),
                {"agent_id", "purpose", "names", "environments", "max_ttl_seconds"},
            )


if __name__ == "__main__":
    unittest.main()
