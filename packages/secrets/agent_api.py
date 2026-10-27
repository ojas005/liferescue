"""The ONLY broker surface an agent runtime may hold (spec 4.2: "facade handed to agents exposes request only").

This module must not import, mention or expose ``use``, ``reveal``, ``ScopedSecret`` or
``GatewayIdentity``; a boundary test (T-09) parses this file to enforce that. It is an API
boundary, not an in-process sandbox: Python introspection can still reach objects, so real
isolation also needs the (deferred) agent sandbox/process boundary.
"""

from __future__ import annotations


class AgentCredentialClient:
    """Bound to one agent id by the broker. Exposes ``request`` and nothing else."""

    __slots__ = ("_request",)

    def __init__(self, request_callable) -> None:
        self._request = request_callable

    def request(self, req):
        """Ask for a credential lease. Returns a LeaseHandle (no value) or raises Denied."""
        return self._request(req)

    def __repr__(self) -> str:
        return "AgentCredentialClient()"
