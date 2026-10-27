"""Test isolation (LR 08 N-03): no provider credentials from the environment, no outbound network."""

import socket

import pytest

_LOCAL = ("127.0.0.1", "::1", "localhost")
NETWORK_ATTEMPTS: list[object] = []


@pytest.fixture(autouse=True)
def _no_provider_credentials(monkeypatch):
    for name in ("NEBIUS_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    real_connect = socket.socket.connect
    real_cc = socket.create_connection

    def _is_local(addr):
        return (
            isinstance(addr, tuple)
            and str(addr[0]) in _LOCAL
            or isinstance(addr, (str, bytes))
        )

    def guarded_connect(self, addr, *a, **kw):
        if not _is_local(addr):
            NETWORK_ATTEMPTS.append(addr)
            raise OSError(f"outbound network blocked in tests: {addr!r}")
        return real_connect(self, addr, *a, **kw)

    def guarded_cc(addr, *a, **kw):
        if not _is_local(addr):
            NETWORK_ATTEMPTS.append(addr)
            raise OSError(f"outbound network blocked in tests: {addr!r}")
        return real_cc(addr, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_cc)


def pytest_sessionfinish(session, exitstatus):
    if NETWORK_ATTEMPTS:
        print(f"\n[N-03] blocked outbound network attempts: {len(NETWORK_ATTEMPTS)}")
