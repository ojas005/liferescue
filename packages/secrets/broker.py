"""CredentialBroker: deny-by-default, task-scoped, short-lived leases (KAN-45 spec 4.2-4.4, 5).

Design rules implemented here:
  * The agent side receives only a ``LeaseHandle`` (``agent_client`` exposes ``request`` only).
    Only registered gateways (``GatewayIdentity``) can call ``use``.
  * PRODUCTION is refused by a constant check that no configuration or policy can override.
  * Expiry is enforced with the MONOTONIC clock; the wall clock is only recorded.
  * Every issue, denial, use, expiry and revocation writes exactly one audit event, with ids only.
  * Every failure (policy, backend, clock, task registry, audit sink) fails closed.
  * Exceptions raised to callers are ``Denied(reason_code)``, raised OUTSIDE ``except`` blocks so
    ``__cause__``/``__context__`` never chain to an exception that might carry a value.
"""
from __future__ import annotations

import hmac
import math
import secrets as _stdlib_secrets
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping, Optional

from .agent_api import AgentCredentialClient
from .audit import AuditEvent, AuditEventType, AuditSink, InMemoryAuditSink, make_event
from .backend import SecretBackend
from .clock import Clock, SystemClock
from .codes import DenialReason, RequestReason, RevokeReason
from .config import BrokerConfig
from .errors import ConfigurationError, Denied, InvalidRequest, PolicyError, UnknownRef
from .leased_values import LeasedValues
from .metrics import Metrics
from .policy import Policy, load_policy
from .secret_types import (
    CallContext,
    CredentialRequest,
    Environment,
    GatewayIdentity,
    LeaseHandle,
    LeaseState,
    ScopedSecret,
    SecretRef,
    SecretValue,
    check_id,
)
from .tasks import TaskRegistry

#: Denial reasons that also raise the alert signal (spec I-7, T-12, T-13).
ALERT_REASONS = frozenset(
    {
        DenialReason.PRODUCTION_REFUSED,
        DenialReason.POLICY_INVALID,
        DenialReason.CLOCK_FAULT,
        DenialReason.BACKEND_UNHEALTHY,
        DenialReason.BACKEND_ERROR,
        DenialReason.TASK_REGISTRY_UNAVAILABLE,
        DenialReason.RATE_LIMITED,
        DenialReason.GLOBAL_RATE_LIMITED,
        DenialReason.INTERNAL_ERROR,
        DenialReason.CONTEXT_MISMATCH,
        DenialReason.CALLER_NOT_GATEWAY,
        DenialReason.HANDLE_TAMPERED,
        DenialReason.UNKNOWN_LEASE,
    }
)

#: Denials of ``use`` that mean "someone presented a handle they should not" -> misuse_suspected.
MISUSE_REASONS = frozenset({DenialReason.CONTEXT_MISMATCH, DenialReason.CALLER_NOT_GATEWAY, DenialReason.HANDLE_TAMPERED})

_WINDOW = 60.0  # seconds, rate-limit window (the spec limits are per minute)


class _Refuse(Exception):
    """Internal control flow: refuse with a reason. Never escapes the broker."""

    def __init__(self, reason: DenialReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass
class _Lease:
    lease_id: str
    ref: SecretRef
    task_id: str
    run_id: str
    agent_id: str
    correlation_id: str
    issued_mono: float
    expires_mono: float
    expires_at: datetime
    state: LeaseState = LeaseState.ISSUED
    uses: int = 0
    value: Optional[SecretValue] = field(default=None, repr=False)


def _ids_of(obj, names: Iterable[str]) -> dict:
    return {n: getattr(obj, n, None) for n in names}


class CredentialBroker:
    def __init__(
        self,
        *,
        backend: SecretBackend,
        policy: Optional[Policy],
        task_registry: TaskRegistry,
        config: Optional[BrokerConfig] = None,
        clock: Optional[Clock] = None,
        audit_sink: Optional[AuditSink] = None,
        alert_handler: Optional[Callable[[AuditEvent], None]] = None,
        gateway_ids: Iterable[str] = (),
        leased_values: Optional[LeasedValues] = None,
        metrics: Optional[Metrics] = None,
    ) -> None:
        # ---- startup guards (spec 5.4): fail closed, do not start in an unsafe configuration ----
        config = config if config is not None else BrokerConfig()
        if not isinstance(config, BrokerConfig):
            raise ConfigurationError("config must be a BrokerConfig")
        if Environment.PRODUCTION in config.served_environments:
            raise ConfigurationError("production can never be served to agents")
        backend_env = getattr(backend, "environment", None)
        if not isinstance(backend_env, Environment):
            raise ConfigurationError("backend must declare its environment")
        if backend_env is Environment.PRODUCTION:
            raise ConfigurationError("a production backend cannot be attached for agent requests")
        if backend_env not in config.served_environments:
            raise ConfigurationError("backend environment is not in served_environments")
        if task_registry is None or not callable(getattr(task_registry, "is_live", None)):
            raise ConfigurationError("a task registry is required (fail closed without one)")
        if policy is not None and not isinstance(policy, Policy):
            raise ConfigurationError("policy must be a Policy")

        self._backend = backend
        self._policy = policy  # None = invalid/unavailable: every request is denied
        self._tasks = task_registry
        self._config = config
        self._clock = clock if clock is not None else SystemClock()
        self.audit_sink: AuditSink = audit_sink if audit_sink is not None else InMemoryAuditSink()
        self._alert_handler = alert_handler
        self.leased_values = leased_values if leased_values is not None else LeasedValues()
        self.metrics = metrics if metrics is not None else Metrics()

        self._lock = threading.RLock()
        self._leases: dict = {}
        self._terminal_order: deque = deque()
        self._agent_hits: dict = {}
        self._global_hits: deque = deque()
        self._last_mono: Optional[float] = None
        self._last_sweep_mono: Optional[float] = None

        self._gateway_tokens: dict = {}
        for gid in gateway_ids:
            self._gateway_tokens[check_id("gateway_id", gid)] = _stdlib_secrets.token_urlsafe(16)
        self._identities_issued = False

    # ------------------------------------------------------------------ public API: wiring --
    def issue_gateway_identities(self) -> dict:
        """Hand the registered gateways their identities. Callable once, at startup, by trusted code."""
        with self._lock:
            if self._identities_issued:
                raise ConfigurationError("gateway identities already issued")
            self._identities_issued = True
            return {gid: GatewayIdentity(gid, tok) for gid, tok in self._gateway_tokens.items()}

    def agent_client(self, agent_id: str) -> AgentCredentialClient:
        """The only broker surface handed to an agent runtime: ``request`` for ONE bound agent id."""
        bound = check_id("agent_id", agent_id)

        def _request(req):
            if not isinstance(req, CredentialRequest) or req.agent_id != bound:
                self._audit_misuse_request(req, DenialReason.CONTEXT_MISMATCH)
                raise Denied(DenialReason.CONTEXT_MISMATCH)
            return self.request(req)

        return AgentCredentialClient(_request)

    def reload_policy(self, loader: Callable[[], Policy] = load_policy) -> None:
        """Replace the policy. On any failure the broker fails closed (policy=None) and re-raises."""
        policy = None
        failed = False
        try:
            policy = loader()
            if not isinstance(policy, Policy):
                failed = True
        except Exception:
            failed = True
        with self._lock:
            self._policy = None if failed else policy
        if failed:
            raise PolicyError("policy reload failed; broker is failing closed")

    # --------------------------------------------------------------------- request ------------
    def request(self, req: CredentialRequest) -> LeaseHandle:
        handle = None
        refusal = None
        with self._lock:
            try:
                handle = self._request_locked(req)
            except _Refuse as r:
                refusal = r.reason
            except Exception:
                refusal = DenialReason.INTERNAL_ERROR
            if refusal is not None:
                self._record_denial(req, refusal)
        if refusal is not None:
            raise Denied(refusal)
        return handle

    def request_wire(self, data: Mapping) -> LeaseHandle:
        """Request from untrusted plain data (e.g. a decoded tool call). Malformed input -> Denied, audited."""
        req = None
        failed = False
        try:
            if not isinstance(data, Mapping):
                raise InvalidRequest("request")
            ttl = data.get("requested_ttl_seconds")
            if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl)):
                raise InvalidRequest("requested_ttl_seconds")
            req = CredentialRequest(
                task_id=data.get("task_id"),
                run_id=data.get("run_id"),
                agent_id=data.get("agent_id"),
                ref=SecretRef.parse(data.get("ref")),
                reason_code=_parse_reason(data.get("reason_code")),
                requested_ttl=None if ttl is None else timedelta(seconds=ttl),
                correlation_id=data.get("correlation_id"),
            )
        except Exception:
            failed = True
        if failed:
            with self._lock:
                self._emit_best_effort(
                    make_event(
                        AuditEventType.LEASE_DENIED,
                        wall=self._safe_wall(),
                        outcome="denied",
                        reason_code=DenialReason.MALFORMED_REQUEST.value,
                        alert=False,
                        task_id=_pick(data, "task_id"),
                        run_id=_pick(data, "run_id"),
                        agent_id=_pick(data, "agent_id"),
                        correlation_id=_pick(data, "correlation_id"),
                    )
                )
                self.metrics.inc("leases_denied", DenialReason.MALFORMED_REQUEST.value)
            raise Denied(DenialReason.MALFORMED_REQUEST)
        return self.request(req)

    def _request_locked(self, req) -> LeaseHandle:
        if not isinstance(req, CredentialRequest):
            raise _Refuse(DenialReason.MALFORMED_REQUEST)
        correlation = req.correlation_id or _new_correlation_id()
        self._emit_strict(self._event(AuditEventType.LEASE_REQUESTED, "requested", req=req, correlation=correlation))
        mono = self._tick()

        # --- hard-coded, non-configurable refusal (spec 4.3 rule 2, I-5, T-14) ---
        if req.ref.environment is Environment.PRODUCTION:
            raise _Refuse(DenialReason.PRODUCTION_REFUSED)

        policy = self._policy
        if policy is None:
            raise _Refuse(DenialReason.POLICY_INVALID)

        self._expire_due(mono)
        self._check_rate(req.agent_id, mono)

        if req.ref.environment not in self._config.served_environments:
            raise _Refuse(DenialReason.ENV_NOT_SERVED)
        grant = policy.find_grant(req.agent_id, req.ref)
        if grant is None:
            raise _Refuse(DenialReason.NO_GRANT)

        ceiling = self._config.max_ttl if grant.max_ttl is None else min(grant.max_ttl, self._config.max_ttl)
        if req.requested_ttl is None:
            # No TTL asked for: use the default, but never more than this grant allows.
            ttl = min(self._config.default_ttl, ceiling)
        else:
            ttl = req.requested_ttl
            if ttl <= timedelta(0):
                raise _Refuse(DenialReason.TTL_INVALID)
            if ttl > ceiling:
                # T-05 pinned behaviour: an EXPLICIT TTL above the maximum is DENIED (no silent clamping).
                raise _Refuse(DenialReason.TTL_EXCEEDS_MAX)

        self._require_task_live(req.task_id, req.run_id, req.agent_id)

        live = [l for l in self._leases.values() if l.task_id == req.task_id and l.state is LeaseState.ISSUED]
        if any(l.ref == req.ref for l in live):
            # T-10/T-11 pinned behaviour: DENY a second lease for (task, ref); no renewal exists.
            raise _Refuse(DenialReason.DUPLICATE_LEASE)
        if len(live) >= self._config.max_leases_per_task:
            raise _Refuse(DenialReason.TASK_LEASE_LIMIT)

        if not self._backend_healthy():
            raise _Refuse(DenialReason.BACKEND_UNHEALTHY)

        value = None
        failure = None
        try:
            value = self._backend.resolve(req.ref, ttl=ttl)
            if not isinstance(value, SecretValue):
                failure = DenialReason.BACKEND_ERROR
        except UnknownRef:
            failure = DenialReason.UNKNOWN_REF
        except Exception:
            failure = DenialReason.BACKEND_ERROR
        if failure is not None:
            raise _Refuse(failure)

        lease = _Lease(
            lease_id=self._new_lease_id(),
            ref=req.ref,
            task_id=req.task_id,
            run_id=req.run_id,
            agent_id=req.agent_id,
            correlation_id=correlation,
            issued_mono=mono,
            expires_mono=mono + ttl.total_seconds(),
            expires_at=self._clock.wall() + ttl,
            value=value,
        )
        self._leases[lease.lease_id] = lease
        self.leased_values.add(lease.lease_id, value)
        try:
            self._emit_strict(self._event(AuditEventType.LEASE_ISSUED, "issued", lease=lease))
        except Exception:
            # cannot audit -> do not hand out a credential
            self._discard_lease_silently(lease)
            raise _Refuse(DenialReason.INTERNAL_ERROR)
        self.metrics.inc("leases_issued", req.ref.purpose.value)
        return LeaseHandle(lease.lease_id, lease.ref, lease.task_id, lease.run_id, lease.agent_id, lease.expires_at)

    # ------------------------------------------------------------------------ use ------------
    def use(self, handle: LeaseHandle, *, caller: GatewayIdentity, context: CallContext) -> ScopedSecret:
        scoped = None
        refusal = None
        with self._lock:
            try:
                scoped = self._use_locked(handle, caller, context)
            except _Refuse as r:
                refusal = r.reason
            except Exception:
                refusal = DenialReason.INTERNAL_ERROR
            if refusal is not None:
                self._record_use_denial(handle, context, refusal)
        if refusal is not None:
            raise Denied(refusal)
        return scoped

    def _use_locked(self, handle, caller, context) -> ScopedSecret:
        mono = self._tick()
        self._maybe_sweep_locked(mono)
        if not isinstance(handle, LeaseHandle) or not isinstance(context, CallContext):
            raise _Refuse(DenialReason.MALFORMED_REQUEST)
        if not self._is_registered_gateway(caller):
            raise _Refuse(DenialReason.CALLER_NOT_GATEWAY)
        lease = self._leases.get(handle.lease_id)
        if lease is None:
            raise _Refuse(DenialReason.UNKNOWN_LEASE)
        if (
            handle.ref != lease.ref
            or handle.task_id != lease.task_id
            or handle.run_id != lease.run_id
            or handle.agent_id != lease.agent_id
            or handle.expires_at != lease.expires_at
        ):
            raise _Refuse(DenialReason.HANDLE_TAMPERED)
        if (context.task_id, context.run_id, context.agent_id) != (lease.task_id, lease.run_id, lease.agent_id):
            raise _Refuse(DenialReason.CONTEXT_MISMATCH)

        self._expire_if_due(lease, mono)
        if lease.state is LeaseState.EXPIRED:
            raise _Refuse(DenialReason.LEASE_EXPIRED)
        if lease.state is LeaseState.REVOKED:
            raise _Refuse(DenialReason.LEASE_REVOKED)

        try:
            self._require_task_live(lease.task_id, lease.run_id, lease.agent_id)
        except _Refuse as r:
            if r.reason is DenialReason.TASK_NOT_LIVE:
                self._revoke_lease(lease, RevokeReason.TASK_END)  # a lease must not outlive its task
            raise
        if lease.uses >= self._config.max_uses_per_lease:
            raise _Refuse(DenialReason.USE_LIMIT_EXCEEDED)

        self._emit_strict(self._event(AuditEventType.LEASE_USED, "used", lease=lease, correlation=context.correlation_id))
        lease.uses += 1
        self.metrics.inc("lease_uses", lease.ref.purpose.value)
        return ScopedSecret(lease.value._duplicate())

    # --------------------------------------------------------------- revoke / sweep ------------
    def revoke(self, lease_id: str, *, reason_code: RevokeReason) -> bool:
        """Revoke one lease. Returns True if a live lease was revoked; terminal/unknown leases are a no-op."""
        _check_revoke_reason(reason_code)
        with self._lock:
            lease = self._leases.get(lease_id) if isinstance(lease_id, str) else None
            if lease is None:
                return False
            self._expire_if_due(lease, self._tick_or_last())
            return self._revoke_lease(lease, reason_code)

    def revoke_task(self, task_id: str, *, reason_code: RevokeReason) -> int:
        """Revoke every live lease of a task (end, failure, cancel, STOP). Call BEFORE marking the task finished."""
        _check_revoke_reason(reason_code)
        with self._lock:
            mono = self._tick_or_last()
            count = 0
            for lease in [l for l in self._leases.values() if l.task_id == task_id]:
                self._expire_if_due(lease, mono)
                if self._revoke_lease(lease, reason_code):
                    count += 1
            return count

    def revoke_all(self, *, reason_code: RevokeReason) -> int:
        """Global STOP / suspected exposure: revoke every live lease."""
        _check_revoke_reason(reason_code)
        with self._lock:
            mono = self._tick_or_last()
            count = 0
            for lease in list(self._leases.values()):
                self._expire_if_due(lease, mono)
                if self._revoke_lease(lease, reason_code):
                    count += 1
            return count

    def maybe_sweep(self) -> int:
        """Sweep only if ``sweep_interval`` has elapsed. The host calls this from its scheduler at least
        every ``sweep_interval`` so expired leases are dropped even if never used again (no thread is started here)."""
        with self._lock:
            return self._maybe_sweep_locked(self._tick_or_last())

    def _maybe_sweep_locked(self, mono: float) -> int:
        last = self._last_sweep_mono
        if last is not None and mono - last < self._config.sweep_interval.total_seconds():
            return 0
        return self._expire_due(mono)

    def sweep(self) -> int:
        """Drop expired leases from memory (spec: sweep interval). Returns the number expired now."""
        with self._lock:
            return self._expire_due(self._tick_or_last())

    # ------------------------------------------------------------------ introspection ----------
    def live_lease_count(self, task_id: Optional[str] = None) -> int:
        with self._lock:
            self._expire_due(self._tick_or_last())
            return sum(
                1 for l in self._leases.values() if l.state is LeaseState.ISSUED and (task_id is None or l.task_id == task_id)
            )

    def lease_state(self, lease_id: str) -> Optional[LeaseState]:
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                return None
            self._expire_if_due(lease, self._tick_or_last())
            return lease.state

    # ------------------------------------------------------------------- internals -------------
    def _tick(self) -> float:
        """Read the monotonic clock; a failing or regressing clock is a fault (fail closed)."""
        fault = False
        mono = 0.0
        try:
            mono = self._clock.monotonic()
            if isinstance(mono, bool) or not isinstance(mono, (int, float)) or not math.isfinite(mono):
                fault = True
            elif self._last_mono is not None and mono < self._last_mono:
                fault = True
        except Exception:
            fault = True
        if fault:
            raise _Refuse(DenialReason.CLOCK_FAULT)
        self._last_mono = float(mono)
        return float(mono)

    def _tick_or_last(self) -> float:
        """For revocation/sweep paths: a clock fault must never prevent revoking. Use the last good reading."""
        try:
            return self._tick()
        except _Refuse:
            return self._last_mono if self._last_mono is not None else 0.0

    def _check_rate(self, agent_id: str, mono: float) -> None:
        cfg = self._config
        hits = self._agent_hits.setdefault(agent_id, deque())
        for dq in (hits, self._global_hits):
            while dq and mono - dq[0] >= _WINDOW:
                dq.popleft()
        if len(hits) >= cfg.agent_rate_limit_per_minute:
            raise _Refuse(DenialReason.RATE_LIMITED)
        if len(self._global_hits) >= cfg.global_rate_limit_per_minute:
            raise _Refuse(DenialReason.GLOBAL_RATE_LIMITED)
        hits.append(mono)
        self._global_hits.append(mono)

    def _require_task_live(self, task_id: str, run_id: str, agent_id: str) -> None:
        live = False
        failed = False
        try:
            live = bool(self._tasks.is_live(task_id, run_id, agent_id))
        except Exception:
            failed = True
        if failed:
            raise _Refuse(DenialReason.TASK_REGISTRY_UNAVAILABLE)
        if not live:
            raise _Refuse(DenialReason.TASK_NOT_LIVE)

    def _backend_healthy(self) -> bool:
        healthy = False
        try:
            healthy = self._backend.health() is True
        except Exception:
            healthy = False
        if not healthy:
            self._emit_best_effort(self._event(AuditEventType.BACKEND_UNHEALTHY, "unhealthy", reason=DenialReason.BACKEND_UNHEALTHY, alert=True))
            self.metrics.inc("backend_unhealthy")
        return healthy

    def _is_registered_gateway(self, caller) -> bool:
        if not isinstance(caller, GatewayIdentity):
            return False
        expected = self._gateway_tokens.get(caller.gateway_id)
        if expected is None or not isinstance(caller._token, str):
            return False
        return hmac.compare_digest(expected.encode(), caller._token.encode())

    def _new_lease_id(self) -> str:
        while True:
            lease_id = _stdlib_secrets.token_urlsafe(16)  # 128 bits, URL-safe, not derived from anything
            if lease_id not in self._leases:
                return lease_id

    # ---- state transitions: each emits exactly one audit event ----
    def _expire_due(self, mono: float) -> int:
        count = 0
        for lease in list(self._leases.values()):
            if self._expire_if_due(lease, mono):
                count += 1
        self._last_sweep_mono = mono
        for agent_id in [a for a, dq in self._agent_hits.items() if not dq or mono - dq[-1] >= _WINDOW]:
            del self._agent_hits[agent_id]  # bound memory: forget agents with no recent requests
        return count

    def _expire_if_due(self, lease: _Lease, mono: float) -> bool:
        if lease.state is not LeaseState.ISSUED or mono < lease.expires_mono:
            return False
        lease.state = LeaseState.EXPIRED
        self._drop_value(lease)
        self._backend_revoke(lease)
        self._emit_best_effort(self._event(AuditEventType.LEASE_EXPIRED, "expired", lease=lease, code="ttl_expired"))
        self.metrics.inc("leases_expired")
        self._note_terminal(lease)
        return True

    def _revoke_lease(self, lease: _Lease, reason: RevokeReason) -> bool:
        if lease.state is not LeaseState.ISSUED:
            return False
        lease.state = LeaseState.REVOKED
        self._drop_value(lease)
        self._backend_revoke(lease)
        self._emit_best_effort(self._event(AuditEventType.LEASE_REVOKED, "revoked", lease=lease, code=reason.value))
        self.metrics.inc("leases_revoked", reason.value)
        self._note_terminal(lease)
        return True

    def _drop_value(self, lease: _Lease) -> None:
        self.leased_values.discard(lease.lease_id)
        if lease.value is not None:
            lease.value.wipe()
            lease.value = None

    def _backend_revoke(self, lease: _Lease) -> None:
        """Best effort at the provider, one retry. The local lease is already dead either way."""
        ok = False
        for _ in range(2):
            try:
                self._backend.revoke(lease.ref, lease.lease_id)
                ok = True
                break
            except Exception:
                ok = False
        if not ok:
            self._emit_best_effort(
                self._event(AuditEventType.BACKEND_UNHEALTHY, "unhealthy", lease=lease, code="backend_revoke_failed", alert=True)
            )
            self.metrics.inc("backend_revoke_failed")

    def _note_terminal(self, lease: _Lease) -> None:
        self._terminal_order.append(lease.lease_id)
        while len(self._terminal_order) > self._config.max_terminal_records:
            old = self._terminal_order.popleft()
            gone = self._leases.get(old)
            if gone is not None and gone.state is not LeaseState.ISSUED:
                del self._leases[old]

    def _discard_lease_silently(self, lease: _Lease) -> None:
        lease.state = LeaseState.REVOKED
        self._drop_value(lease)
        self._backend_revoke(lease)
        self._leases.pop(lease.lease_id, None)

    # ---- audit plumbing ----
    def _event(
        self,
        event_type: AuditEventType,
        outcome: str,
        *,
        req: Optional[CredentialRequest] = None,
        lease: Optional[_Lease] = None,
        reason: Optional[DenialReason] = None,
        code: Optional[str] = None,
        alert: Optional[bool] = None,
        correlation: Optional[str] = None,
    ) -> AuditEvent:
        """Build an audit event from a request or a lease (ids and names only)."""
        src = lease if lease is not None else req
        ids: dict = {}
        if src is not None:
            ids = dict(task_id=src.task_id, run_id=src.run_id, agent_id=src.agent_id, ref=src.ref.to_string())
        if lease is not None:
            ids["lease_id"] = lease.lease_id
            correlation = correlation or lease.correlation_id
        if reason is not None:
            code = reason.value
            if alert is None:
                alert = reason in ALERT_REASONS
        return make_event(
            event_type,
            wall=self._safe_wall(),
            outcome=outcome,
            correlation_id=correlation,
            reason_code=code,
            alert=bool(alert),
            **ids,
        )

    def _emit_strict(self, event: AuditEvent) -> None:
        """Emit or raise: used where proceeding without an audit record would be unsafe."""
        self.audit_sink.emit(event)
        self._maybe_alert(event)

    def _emit_best_effort(self, event: AuditEvent) -> None:
        try:
            self.audit_sink.emit(event)
        except Exception:
            self.metrics.inc("audit_sink_failures")
        self._maybe_alert(event)

    def _maybe_alert(self, event: AuditEvent) -> None:
        if event.alert:
            self.metrics.inc("alerts", event.reason_code or "")
            if self._alert_handler is not None:
                try:
                    self._alert_handler(event)
                except Exception:
                    self.metrics.inc("alert_handler_failures")

    def _record_denial(self, req, reason: DenialReason) -> None:
        fields = _ids_of(req, ("task_id", "run_id", "agent_id")) if isinstance(req, CredentialRequest) else {}
        ref = req.ref.to_string() if isinstance(req, CredentialRequest) else None
        event = make_event(
            AuditEventType.LEASE_DENIED,
            wall=self._safe_wall(),
            outcome="denied",
            correlation_id=getattr(req, "correlation_id", None) if isinstance(req, CredentialRequest) else None,
            ref=ref,
            reason_code=reason.value,
            alert=reason in ALERT_REASONS,
            **fields,
        )
        self._emit_best_effort(event)
        self.metrics.inc("leases_denied", reason.value)

    def _record_use_denial(self, handle, context, reason: DenialReason) -> None:
        lease = self._leases.get(getattr(handle, "lease_id", None)) if isinstance(getattr(handle, "lease_id", None), str) else None
        ids = {}
        if lease is not None:
            ids = dict(task_id=lease.task_id, run_id=lease.run_id, agent_id=lease.agent_id, lease_id=lease.lease_id, ref=lease.ref.to_string())
        else:
            ids = dict(agent_id=getattr(context, "agent_id", None), task_id=getattr(context, "task_id", None), run_id=getattr(context, "run_id", None))
        misuse = reason in MISUSE_REASONS
        event = make_event(
            AuditEventType.MISUSE_SUSPECTED if misuse else AuditEventType.LEASE_DENIED,
            wall=self._safe_wall(),
            outcome="suspected" if misuse else "denied",
            correlation_id=getattr(context, "correlation_id", None),
            reason_code=reason.value,
            alert=reason in ALERT_REASONS,
            **ids,
        )
        self._emit_best_effort(event)
        self.metrics.inc("misuse_suspected" if misuse else "uses_denied", reason.value)

    def _audit_misuse_request(self, req, reason: DenialReason) -> None:
        with self._lock:
            ids = _ids_of(req, ("task_id", "run_id", "agent_id")) if isinstance(req, CredentialRequest) else {}
            self._emit_best_effort(
                make_event(
                    AuditEventType.MISUSE_SUSPECTED,
                    wall=self._safe_wall(),
                    outcome="suspected",
                    reason_code=reason.value,
                    alert=True,
                    **ids,
                )
            )
            self.metrics.inc("misuse_suspected", reason.value)

    def _safe_wall(self) -> datetime:
        try:
            return self._clock.wall()
        except Exception:
            return datetime.fromtimestamp(0, tz=timezone.utc)


# ---------------------------------------------------------------------------- helpers ---------
def _new_correlation_id() -> str:
    return "c-" + _stdlib_secrets.token_hex(8)


def _parse_reason(value) -> RequestReason:
    for member in RequestReason:
        if isinstance(value, str) and member.value == value:
            return member
    raise InvalidRequest("reason_code")


def _check_revoke_reason(reason) -> None:
    if not isinstance(reason, RevokeReason):
        raise InvalidRequest("reason_code")


def _pick(data, key):
    if isinstance(data, Mapping):
        v = data.get(key)
        return v if isinstance(v, str) else None
    return None
