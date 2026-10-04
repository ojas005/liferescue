"""Closed lists of codes used in requests, denials, revocations and audit events (KAN-45).

Every reason that crosses a boundary (exception, audit event, log line) is one of these
enum values, never free text, so no request content or secret can ride along in a reason.
"""
from __future__ import annotations

from enum import Enum


class RequestReason(Enum):
    """Why an agent asks for a credential. Closed list; extended only by a reviewed PR.

    PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL: the spec asks for "a closed list" but
    does not name its members; these four are a minimal starting set.
    """

    MODEL_CALL = "model_call"
    WEB_SEARCH_CALL = "web_search_call"
    DB_ACCESS = "db_access"
    TEST_RUN = "test_run"


class DenialReason(Enum):
    MALFORMED_REQUEST = "malformed_request"
    PRODUCTION_REFUSED = "production_refused"
    ENV_NOT_SERVED = "environment_not_served"
    NO_GRANT = "no_grant"
    TTL_INVALID = "ttl_invalid"
    TTL_EXCEEDS_MAX = "ttl_exceeds_max"
    TASK_NOT_LIVE = "task_not_live"
    TASK_REGISTRY_UNAVAILABLE = "task_registry_unavailable"
    DUPLICATE_LEASE = "duplicate_lease"
    TASK_LEASE_LIMIT = "task_lease_limit"
    RATE_LIMITED = "rate_limited"
    GLOBAL_RATE_LIMITED = "global_rate_limited"
    POLICY_INVALID = "policy_invalid"
    BACKEND_UNHEALTHY = "backend_unhealthy"
    BACKEND_ERROR = "backend_error"
    UNKNOWN_REF = "unknown_ref"
    CLOCK_FAULT = "clock_fault"
    UNKNOWN_LEASE = "unknown_lease"
    LEASE_EXPIRED = "lease_expired"
    LEASE_REVOKED = "lease_revoked"
    USE_LIMIT_EXCEEDED = "use_limit_exceeded"
    CONTEXT_MISMATCH = "context_mismatch"
    CALLER_NOT_GATEWAY = "caller_not_gateway"
    HANDLE_TAMPERED = "handle_tampered"
    INTERNAL_ERROR = "internal_error"


class RevokeReason(Enum):
    TASK_END = "task_end"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    STOP = "stop"
    AGENT_SUSPENDED = "agent_suspended"
    OWNER_ACTION = "owner_action"
    SUSPECTED_EXPOSURE = "suspected_exposure"
    MISUSE = "misuse"
