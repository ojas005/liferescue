"""Core types for the secret-management slice (KAN-45 spec section 4.1).

Named ``secret_types`` (spec sketch: ``types.py``) so the module can never shadow the
standard-library ``types`` module if a directory is ever put on ``sys.path``.

Key properties:
  * ``SecretRef`` is a name, never a value.
  * ``SecretValue`` cannot be printed, formatted, pickled, copied or JSON-encoded. The only
    exit is ``with value.reveal() as raw:``.
  * ``LeaseHandle`` carries no value and is safe to put in prompts, logs and databases.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from .codes import RequestReason
from .errors import InvalidRequest, InvalidSecretRef, SecretWiped

REDACTED = "[REDACTED]"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


class Environment(Enum):
    MOCK = "mock"  # in-memory, generated values (this slice)
    TEST = "test"  # reserved: test credentials issued by a human out of band (not implemented)
    PRODUCTION = "production"  # exists only so that it can be REFUSED


class Purpose(Enum):
    """Closed list, extended only by a reviewed PR, with its consumer."""

    MODEL_INFERENCE = "model_inference"
    WEB_SEARCH = "web_search"
    DB_APP = "db_app"


def check_id(field_name: str, value: object) -> str:
    """Validate an identifier (task/run/agent/correlation id). Never echoes the value."""
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise InvalidRequest(field_name)
    return value


@dataclass(frozen=True)
class SecretRef:
    """A name, never a value: ``secretref://<environment>/<purpose>/<name>``."""

    environment: Environment
    purpose: Purpose
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.environment, Environment):
            raise InvalidSecretRef("environment")
        if not isinstance(self.purpose, Purpose):
            raise InvalidSecretRef("purpose")
        if not isinstance(self.name, str) or not _NAME_RE.match(self.name):
            raise InvalidSecretRef("name")

    def to_string(self) -> str:
        return f"secretref://{self.environment.value}/{self.purpose.value}/{self.name}"

    @classmethod
    def parse(cls, text: object) -> SecretRef:
        """Parse ``secretref://env/purpose/name``. Unknown parts raise InvalidSecretRef (fail closed)."""
        prefix = "secretref://"
        if not isinstance(text, str) or not text.startswith(prefix) or len(text) > 200:
            raise InvalidSecretRef("ref")
        parts = text[len(prefix) :].split("/")
        if len(parts) != 3:
            raise InvalidSecretRef("ref")
        env_s, purpose_s, name = parts
        env = _lookup(Environment, env_s, "environment")
        purpose = _lookup(Purpose, purpose_s, "purpose")
        return cls(env, purpose, name)


def _lookup(enum_cls: type, value: str, field_name: str):
    for member in enum_cls:
        if member.value == value:
            return member
    raise InvalidSecretRef(field_name)


class _Reveal:
    """Context manager returned by ``SecretValue.reveal()``."""

    __slots__ = ("_owner",)

    def __init__(self, owner: SecretValue) -> None:
        self._owner = owner

    def __enter__(self) -> str:
        return self._owner._decode()

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False  # never swallow exceptions; never attach the value to them

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return REDACTED


class SecretValue:
    """Holds a value. repr/str/format/pickle/copy/deepcopy are disabled or return ``[REDACTED]``.

    Only ``reveal()`` returns the raw value, only inside ``with value.reveal() as raw:``.
    ``wipe()`` zeroes the internal buffer (best effort: Python ``str`` objects obtained from
    ``reveal()`` are immutable and cannot be wiped; keep them short-lived).
    """

    __slots__ = ("__weakref__", "_buf", "_wiped")

    def __init__(self, raw: str) -> None:
        if not isinstance(raw, str) or not raw:
            raise TypeError("SecretValue requires a non-empty str")
        self._buf = bytearray(raw.encode("utf-8"))
        self._wiped = False

    def reveal(self) -> _Reveal:
        return _Reveal(self)

    def _decode(self) -> str:
        if self._wiped:
            raise SecretWiped("secret value has been wiped")
        return bytes(self._buf).decode("utf-8")

    def _duplicate(self) -> SecretValue:
        """Internal: independent copy for one scoped use (so wiping it does not wipe the lease copy)."""
        return SecretValue(self._decode())

    def wipe(self) -> None:
        for i in range(len(self._buf)):
            self._buf[i] = 0
        self._wiped = True

    @property
    def wiped(self) -> bool:
        return self._wiped

    # ---- every serialisation / display path is closed -------------------------------
    def __repr__(self) -> str:
        return REDACTED

    def __str__(self) -> str:
        return REDACTED

    def __format__(self, format_spec: str) -> str:
        return REDACTED

    def __reduce__(self):
        raise TypeError("SecretValue cannot be pickled")

    def __reduce_ex__(self, protocol):
        raise TypeError("SecretValue cannot be pickled")

    def __getstate__(self):
        raise TypeError("SecretValue cannot be serialised")

    def __copy__(self):
        raise TypeError("SecretValue cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("SecretValue cannot be copied")

    def __del__(self) -> None:  # best-effort wipe when dropped
        with contextlib.suppress(
            Exception
        ):  # pragma: no cover - best effort in __del__
            self.wipe()


@dataclass(frozen=True)
class CredentialRequest:
    """A request for a task-scoped credential. Contains names and ids only."""

    task_id: str
    run_id: str
    agent_id: str  # e.g. "LR-06"
    ref: SecretRef
    reason_code: RequestReason
    requested_ttl: timedelta | None = None  # None -> BrokerConfig.default_ttl
    correlation_id: str | None = (
        None  # PROPOSED addition: spec audit fields include a correlation id
    )

    def __post_init__(self) -> None:
        check_id("task_id", self.task_id)
        check_id("run_id", self.run_id)
        check_id("agent_id", self.agent_id)
        if not isinstance(self.ref, SecretRef):
            raise InvalidRequest("ref")
        if not isinstance(self.reason_code, RequestReason):
            raise InvalidRequest("reason_code")
        if self.requested_ttl is not None and not isinstance(
            self.requested_ttl, timedelta
        ):
            raise InvalidRequest("requested_ttl")
        if self.correlation_id is not None:
            check_id("correlation_id", self.correlation_id)


class LeaseState(Enum):
    ISSUED = "issued"
    EXPIRED = "expired"
    REVOKED = "revoked"
    DENIED = "denied"


@dataclass(frozen=True)
class LeaseHandle:
    """Safe to put in prompts, logs, DB: carries no value."""

    lease_id: str  # random, 128 bit, unguessable
    ref: SecretRef
    task_id: str
    run_id: str
    agent_id: str
    expires_at: (
        datetime  # wall clock, informational; enforcement uses a monotonic clock
    )


@dataclass(frozen=True)
class CallContext:
    """What the gateway says it is acting for on a ``use`` call.

    PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL: the spec's ``use(handle, *, caller)`` has no
    way to express "the task/run/agent on whose behalf this call is made", which T-08 and
    invariant I-3 need. This explicit context is the smallest addition that makes them testable.
    """

    task_id: str
    run_id: str
    agent_id: str
    correlation_id: str | None = None


@dataclass(frozen=True)
class GatewayIdentity:
    """A registered gateway (Model/Tool). Created by the broker at startup, never by agents.

    The token is unguessable and never shown by repr; ``use`` compares it in constant time.
    """

    gateway_id: str
    _token: str = field(repr=False, compare=False, default="")

    def __repr__(self) -> str:
        return f"GatewayIdentity(gateway_id={self.gateway_id!r})"


class ScopedSecret:
    """Context manager returned by ``CredentialBroker.use``: yields a SecretValue for one call.

    The yielded value is an independent copy, wiped on exit (best effort).
    Rule for gateway authors: call ``reveal()`` only inside the provider call; never put the
    raw value in a return object.
    """

    __slots__ = ("_entered", "_value")

    def __init__(self, value: SecretValue) -> None:
        self._value = value
        self._entered = False

    def __enter__(self) -> SecretValue:
        if self._entered:
            raise SecretWiped("scoped secret already used")
        self._entered = True
        return self._value

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._value.wipe()
        return False

    def __repr__(self) -> str:
        return "ScopedSecret([REDACTED])"
