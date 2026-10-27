"""Reusable SecretBackend conformance suite (KAN-45 spec T-27, step 7).

Any future ``SecretBackend`` (deferred real adapters included) must pass this suite. Use it as a mixin:

    class MyBackendConformance(BackendConformanceMixin, unittest.TestCase):
        ISOLATED = False                      # True only for in-process backends that must not touch env/files/network
        def make_backend(self): ...           # a fresh, healthy backend serving ``self.ENVIRONMENT``
        def provision(self, backend, ref, value): ...   # make ``ref`` resolvable with ``value`` (a random canary)
        def break_backend(self, backend): ... # optional: make health() return False
        def heal_backend(self, backend): ...

The suite never uses a real credential: values are random canaries generated per test.
"""

from __future__ import annotations

import builtins
import copy
import pickle
import socket
import threading
from datetime import timedelta
from unittest import mock

from .errors import BackendError, UnknownRef
from .secret_types import Environment, Purpose, SecretRef, SecretValue
from .testing import make_canary


class BackendConformanceMixin:
    ENVIRONMENT = Environment.MOCK
    ISOLATED = False
    TTL = timedelta(minutes=5)

    # ---- hooks a concrete suite must provide ----
    def make_backend(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def provision(self, backend, ref, value):  # pragma: no cover - abstract
        raise NotImplementedError

    def break_backend(self, backend):
        self.skipTest("backend cannot simulate an outage")

    def heal_backend(self, backend):  # pragma: no cover
        pass

    # ---- helpers ----
    def ref(self, name="mock-conformance-key"):
        return SecretRef(self.ENVIRONMENT, Purpose.MODEL_INFERENCE, name)

    def ready(self, name="mock-conformance-key"):
        backend = self.make_backend()
        canary = make_canary()
        ref = self.ref(name)
        self.provision(backend, ref, canary)
        return backend, ref, canary

    # ---- the contract ----
    def test_conformance_declares_a_non_production_environment(self):
        backend = self.make_backend()
        self.assertIsInstance(backend.environment, Environment)
        self.assertIs(backend.environment, self.ENVIRONMENT)
        self.assertIsNot(backend.environment, Environment.PRODUCTION)

    def test_conformance_issue_returns_secret_value_with_the_provisioned_value(self):
        backend, ref, canary = self.ready()
        value = backend.resolve(ref, ttl=self.TTL)
        self.assertIsInstance(value, SecretValue)
        with value.reveal() as raw:
            self.assertEqual(raw, canary)

    def test_conformance_each_resolve_returns_an_independent_object(self):
        backend, ref, canary = self.ready()
        a, b = backend.resolve(ref, ttl=self.TTL), backend.resolve(ref, ttl=self.TTL)
        self.assertIsNot(a, b)
        a.wipe()
        with b.reveal() as raw:
            self.assertEqual(raw, canary)

    def test_conformance_value_never_appears_in_repr_str_format_pickle_copy(self):
        backend, ref, canary = self.ready()
        value = backend.resolve(ref, ttl=self.TTL)
        for text in (
            repr(value),
            str(value),
            format(value),
            f"{value}",
            repr([value]),
            repr({"v": value}),
        ):
            self.assertNotIn(canary, text)
        for fn in (pickle.dumps, copy.copy, copy.deepcopy):
            with self.assertRaises(TypeError):
                fn(value)

    def test_conformance_ttl_must_be_positive(self):
        backend, ref, canary = self.ready()
        for bad in (timedelta(0), timedelta(seconds=-1)):
            with self.assertRaises(BackendError) as ctx:
                backend.resolve(ref, ttl=bad)
            self.assertNotIn(canary, str(ctx.exception) + repr(ctx.exception))
        backend.resolve(ref, ttl=timedelta(seconds=1))

    def test_conformance_unknown_ref_raises_unknown_ref_without_leaking(self):
        backend, _ref, canary = self.ready()
        with self.assertRaises(UnknownRef) as ctx:
            backend.resolve(self.ref("mock-not-provisioned"), ttl=self.TTL)
        self.assertNotIn(canary, str(ctx.exception) + repr(ctx.exception))
        self.assertNotIn("not-provisioned", str(ctx.exception))

    def test_conformance_wrong_environment_refs_are_refused(self):
        backend, _ref, _canary = self.ready()
        for env in Environment:
            if env is self.ENVIRONMENT:
                continue
            with self.assertRaises(BackendError):
                backend.resolve(
                    SecretRef(env, Purpose.MODEL_INFERENCE, "mock-conformance-key"),
                    ttl=self.TTL,
                )

    def test_conformance_revoke_is_idempotent_and_tolerates_unknown_leases(self):
        backend, ref, _canary = self.ready()
        backend.revoke(ref, "lease-id-that-never-existed-0000")
        backend.revoke(ref, "lease-id-that-never-existed-0000")
        backend.resolve(ref, ttl=self.TTL)
        backend.revoke(ref, "another-lease-id-0000000")

    def test_conformance_health_is_a_bool_and_reports_outages(self):
        backend, ref, canary = self.ready()
        self.assertIs(backend.health(), True)
        self.break_backend(backend)
        self.assertIs(backend.health(), False)
        with self.assertRaises(BackendError) as ctx:
            backend.resolve(ref, ttl=self.TTL)
        self.assertNotIn(canary, str(ctx.exception) + repr(ctx.exception))
        self.heal_backend(backend)
        self.assertIs(backend.health(), True)

    def test_conformance_concurrent_resolves_are_safe(self):
        backend, ref, canary = self.ready()
        results, errors = [], []
        barrier = threading.Barrier(16)

        def work():
            barrier.wait()
            try:
                v = backend.resolve(ref, ttl=self.TTL)
                with v.reveal() as raw:
                    results.append(raw)
            except BaseException as exc:  # pragma: no cover - would fail the test  # noqa: BLE001 - fail-closed boundary: any failure becomes a denial/fallback and never propagates
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(16)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(results, [canary] * 16)

    def test_conformance_isolated_backends_touch_no_env_file_or_network(self):
        if not self.ISOLATED:
            self.skipTest(
                "backend is not declared ISOLATED (a real adapter legitimately uses the network)"
            )
        import os

        class Trap:
            def __getattr__(self, name):
                raise AssertionError("backend touched env/file/network")

            def __call__(self, *a, **k):
                raise AssertionError("backend touched env/file/network")

            def __getitem__(self, k):
                raise AssertionError("backend touched env/file/network")

            def __contains__(self, k):
                raise AssertionError("backend touched env/file/network")

            def __iter__(self):
                raise AssertionError("backend touched env/file/network")

        backend, ref, _canary = self.ready()
        with (
            mock.patch.object(os, "environ", Trap()),
            mock.patch.object(os, "getenv", Trap()),
            mock.patch.object(builtins, "open", Trap()),
            mock.patch.object(socket, "socket", Trap()),
            mock.patch.object(socket, "getaddrinfo", Trap()),
        ):
            backend.resolve(ref, ttl=self.TTL)
            backend.revoke(ref, "lease-id-0000000000000")
            backend.health()
