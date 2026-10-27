"""KAN-45 step 7 tests: backend conformance suite (T-27) run against the mock backend, plus proof that the
suite fails for deliberately broken backends and that the broker works with any conforming backend."""

import io
import unittest
from datetime import timedelta

from packages.secrets.codes import RevokeReason
from packages.secrets.conformance import BackendConformanceMixin
from packages.secrets.errors import BackendError
from packages.secrets.memory_backend import InMemoryBackend
from packages.secrets.secret_types import Environment, SecretValue
from tests.security.fixtures_broker import Rig


class MockBackendConformance(BackendConformanceMixin, unittest.TestCase):
    ENVIRONMENT = Environment.MOCK
    ISOLATED = True

    def make_backend(self):
        return InMemoryBackend()

    def provision(self, backend, ref, value):
        backend.provision(ref, value)

    def break_backend(self, backend):
        backend.set_healthy(False)

    def heal_backend(self, backend):
        backend.set_healthy(True)


def run_suite_against(backend_cls, **attrs):
    """Run the conformance mixin against ``backend_cls``; returns the unittest result."""

    class Candidate(BackendConformanceMixin, unittest.TestCase):
        ENVIRONMENT = Environment.MOCK
        ISOLATED = attrs.get("isolated", False)

        def make_backend(self):
            return backend_cls()

        def provision(self, backend, ref, value):
            backend.provision(ref, value)

        def break_backend(self, backend):
            backend.set_healthy(False)

        def heal_backend(self, backend):
            backend.set_healthy(True)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Candidate)
    return unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)


def failed_names(result):
    return {t.id().rsplit(".", 1)[-1] for t, _ in result.failures + result.errors}


class SuiteDetectsBrokenBackends(unittest.TestCase):
    """The suite must FAIL for non-conforming backends (otherwise it proves nothing)."""

    def test_conforming_candidate_passes_the_same_harness(self):
        result = run_suite_against(InMemoryBackend, isolated=True)
        self.assertTrue(result.wasSuccessful(), failed_names(result))
        self.assertGreaterEqual(result.testsRun, 11)

    def test_backend_returning_plain_str_fails(self):
        class PlainStr(InMemoryBackend):
            def resolve(self, ref, *, ttl):
                return super().resolve(ref, ttl=ttl)._decode()

        names = failed_names(run_suite_against(PlainStr))
        self.assertIn(
            "test_conformance_issue_returns_secret_value_with_the_provisioned_value",
            names,
        )

    def test_backend_that_accepts_non_positive_ttl_fails(self):
        class NoTtlCheck(InMemoryBackend):
            def resolve(self, ref, *, ttl):
                return super().resolve(ref, ttl=abs(ttl) + timedelta(seconds=1))

        self.assertIn(
            "test_conformance_ttl_must_be_positive",
            failed_names(run_suite_against(NoTtlCheck)),
        )

    def test_backend_whose_errors_leak_the_value_fails(self):
        class LeakyErrors(InMemoryBackend):
            def resolve(self, ref, *, ttl):
                if not self._healthy:
                    raise BackendError(f"down; last value was {self._values.get(ref)}")
                return super().resolve(ref, ttl=ttl)

        self.assertIn(
            "test_conformance_health_is_a_bool_and_reports_outages",
            failed_names(run_suite_against(LeakyErrors)),
        )

    def test_backend_sharing_one_secretvalue_fails(self):
        class Shared(InMemoryBackend):
            _cache = {}  # noqa: RUF012 - test deliberately shares mutable state

            def resolve(self, ref, *, ttl):
                v = super().resolve(ref, ttl=ttl)
                return self._cache.setdefault(ref, v)

        self.assertIn(
            "test_conformance_each_resolve_returns_an_independent_object",
            failed_names(run_suite_against(Shared)),
        )

    def test_backend_that_never_raises_unknown_ref_fails(self):
        class Anything(InMemoryBackend):
            def resolve(self, ref, *, ttl):
                return SecretValue("mock-anything-" + "x" * 20)

        self.assertIn(
            "test_conformance_unknown_ref_raises_unknown_ref_without_leaking",
            failed_names(run_suite_against(Anything)),
        )

    def test_backend_that_reads_the_environment_fails_isolation(self):
        import os

        class ReadsEnv(InMemoryBackend):
            def resolve(self, ref, *, ttl):
                os.environ.get("HOME")
                return super().resolve(ref, ttl=ttl)

        self.assertIn(
            "test_conformance_isolated_backends_touch_no_env_file_or_network",
            failed_names(run_suite_against(ReadsEnv, isolated=True)),
        )

    def test_backend_whose_revoke_raises_for_unknown_lease_fails(self):
        class StrictRevoke(InMemoryBackend):
            def revoke(self, ref, lease_id):
                raise KeyError("unknown lease")

        self.assertIn(
            "test_conformance_revoke_is_idempotent_and_tolerates_unknown_leases",
            failed_names(run_suite_against(StrictRevoke)),
        )


class BrokerWorksWithAnyConformingBackend(unittest.TestCase):
    def test_broker_uses_backend_through_the_protocol_only(self):
        rig = Rig()
        handle = rig.request()
        with rig.use(handle) as secret, secret.reveal() as raw:
            self.assertEqual(raw, rig.canaries[handle.ref])
        rig.broker.revoke_all(reason_code=RevokeReason.STOP)
        self.assertEqual(rig.backend.revoked[-1][1], handle.lease_id)


if __name__ == "__main__":
    unittest.main()
