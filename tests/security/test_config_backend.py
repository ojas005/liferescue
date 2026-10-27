"""KAN-45 step 3 (part 1): config defaults/validation, mock backend isolation (T-15)."""

import builtins
import json
import os
import socket
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from packages.secrets.config import CONFIG_FIELD_NAMES, BrokerConfig
from packages.secrets.errors import BackendError, ConfigurationError, UnknownRef
from packages.secrets.memory_backend import MOCK_PREFIX, InMemoryBackend
from packages.secrets.secret_types import Environment, Purpose, SecretRef, SecretValue
from packages.secrets.testing import make_canary

REF = SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key")


class ConfigDefaults(unittest.TestCase):
    def test_spec_defaults_are_configuration_not_policy(self):
        cfg = BrokerConfig()
        self.assertEqual(cfg.default_ttl, timedelta(minutes=15))
        self.assertEqual(cfg.max_ttl, timedelta(minutes=30))
        self.assertEqual(cfg.max_ttl_real_credential, timedelta(minutes=60))
        self.assertEqual(cfg.max_leases_per_task, 4)
        self.assertEqual(cfg.max_uses_per_lease, 200)
        self.assertEqual(cfg.sweep_interval, timedelta(seconds=30))
        self.assertEqual(cfg.agent_rate_limit_per_minute, 30)
        self.assertEqual(cfg.served_environments, frozenset({Environment.MOCK}))

    def test_values_can_be_changed_without_code_edits(self):
        cfg = BrokerConfig.from_mapping(
            {
                "default_ttl_seconds": 60,
                "max_ttl_seconds": 120,
                "max_leases_per_task": 2,
                "agent_rate_limit_per_minute": 5,
            }
        )
        self.assertEqual(cfg.default_ttl, timedelta(seconds=60))
        self.assertEqual(cfg.max_ttl, timedelta(seconds=120))
        self.assertEqual(cfg.max_leases_per_task, 2)
        self.assertEqual(cfg.agent_rate_limit_per_minute, 5)

    def test_from_json_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            p.write_text(json.dumps({"default_ttl_seconds": 30, "max_ttl_seconds": 90}))
            self.assertEqual(
                BrokerConfig.from_json_file(p).default_ttl, timedelta(seconds=30)
            )
            p.write_text("{not json")
            with self.assertRaises(ConfigurationError):
                BrokerConfig.from_json_file(p)
            with self.assertRaises(ConfigurationError):
                BrokerConfig.from_json_file(Path(d) / "missing.json")

    def test_invalid_values_rejected(self):
        for bad in [
            {"default_ttl_seconds": 0},
            {"default_ttl_seconds": -1},
            {"default_ttl_seconds": "15"},
            {"default_ttl_seconds": True},
            {"default_ttl_seconds": 4000},  # > max
            {"max_ttl_seconds": 7200},  # > real-credential max
            {"max_leases_per_task": 0},
            {"max_leases_per_task": 1.5},
            {"max_uses_per_lease": True},
            {"unknown_key": 1},
            {"served_environments": []},
            {"served_environments": ["staging"]},
            {"served_environments": "mock"},
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigurationError):
                    BrokerConfig.from_mapping(bad)

    def test_production_can_never_be_configured_T14(self):
        for envs in (["production"], ["mock", "production"], [Environment.PRODUCTION]):
            with self.assertRaises(ConfigurationError):
                BrokerConfig.from_mapping({"served_environments": envs}) if isinstance(
                    envs[0], str
                ) else BrokerConfig(served_environments=frozenset(envs))

    def test_unknown_key_name_is_not_echoed(self):
        canary = make_canary()
        with self.assertRaises(ConfigurationError) as ctx:
            BrokerConfig.from_mapping({canary: 1})
        self.assertNotIn(canary, str(ctx.exception))

    def test_readme_documents_every_config_field(self):
        readme = (
            Path(__file__).resolve().parents[2] / "packages" / "secrets" / "README.md"
        ).read_text()
        for key in BrokerConfig().as_mapping():
            self.assertIn(key, readme, f"README must document config field {key}")
        self.assertTrue(CONFIG_FIELD_NAMES)


class _Trap:
    """Fails the test on any access."""

    def __init__(self, what):
        self.what = what

    def __getattr__(self, name):
        raise AssertionError(f"mock backend touched {self.what}")

    def __call__(self, *a, **k):
        raise AssertionError(f"mock backend touched {self.what}")

    def __getitem__(self, k):
        raise AssertionError(f"mock backend touched {self.what}")

    def __iter__(self):
        raise AssertionError(f"mock backend touched {self.what}")

    def __contains__(self, k):
        raise AssertionError(f"mock backend touched {self.what}")


class MockBackendBehaviour(unittest.TestCase):
    def test_generated_values_are_random_prefixed_and_distinct(self):
        a, b = InMemoryBackend(), InMemoryBackend()
        a.provision(REF)
        b.provision(REF)
        with (
            a.resolve(REF, ttl=timedelta(minutes=1)).reveal() as va,
            b.resolve(REF, ttl=timedelta(minutes=1)).reveal() as vb,
        ):
            self.assertTrue(va.startswith(MOCK_PREFIX))
            self.assertGreaterEqual(len(va), len(MOCK_PREFIX) + 24)
            self.assertNotEqual(va, vb)

    def test_resolve_returns_secret_value_not_str(self):
        be = InMemoryBackend()
        be.provision(REF)
        self.assertIsInstance(be.resolve(REF, ttl=timedelta(minutes=1)), SecretValue)

    def test_declares_mock_and_refuses_other_environments(self):
        be = InMemoryBackend()
        self.assertIs(be.environment, Environment.MOCK)
        for env in (Environment.TEST, Environment.PRODUCTION):
            other = SecretRef(env, Purpose.DB_APP, "mock-db-app-key")
            with self.assertRaises(BackendError):
                be.provision(other)
            with self.assertRaises(BackendError):
                be.resolve(other, ttl=timedelta(minutes=1))

    def test_unknown_ref_and_bad_ttl(self):
        be = InMemoryBackend()
        with self.assertRaises(UnknownRef):
            be.resolve(REF, ttl=timedelta(minutes=1))
        be.provision(REF)
        with self.assertRaises(BackendError):
            be.resolve(REF, ttl=timedelta(0))

    def test_isolation_no_environment_file_or_network_access_T15(self):
        be = InMemoryBackend()
        with (
            mock.patch.object(os, "environ", _Trap("os.environ")),
            mock.patch.object(os, "getenv", _Trap("os.getenv")),
            mock.patch.object(builtins, "open", _Trap("open()")),
            mock.patch.object(socket, "socket", _Trap("socket")),
            mock.patch.object(socket, "create_connection", _Trap("create_connection")),
            mock.patch.object(socket, "getaddrinfo", _Trap("getaddrinfo")),
        ):
            be.provision(REF)
            be.provision(REF, make_canary())
            be.resolve(REF, ttl=timedelta(minutes=1))
            be.revoke(REF, "lease-1")
            self.assertTrue(be.health())

    def test_isolation_source_does_not_import_network_or_env_modules(self):
        import ast

        src = (
            Path(__file__).resolve().parents[2]
            / "packages"
            / "secrets"
            / "memory_backend.py"
        ).read_text()
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for banned in (
            "os",
            "socket",
            "http",
            "urllib",
            "requests",
            "subprocess",
            "pathlib",
            "shutil",
            "ssl",
        ):
            self.assertNotIn(banned, imported)

    def test_health_and_outage(self):
        be = InMemoryBackend()
        be.provision(REF)
        be.set_healthy(False)
        self.assertFalse(be.health())
        with self.assertRaises(BackendError):
            be.resolve(REF, ttl=timedelta(minutes=1))


if __name__ == "__main__":
    unittest.main()
