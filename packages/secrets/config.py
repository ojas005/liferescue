"""Broker configuration (KAN-45 spec section 5.2, step 3).

Every number below is a PROPOSED default taken from the spec. They are configuration values,
NOT hard-coded policy: change them with ``BrokerConfig(...)``, ``from_mapping`` or
``from_json_file`` (no environment variables are read). The ONLY hard-coded security rule is
the refusal of ``Environment.PRODUCTION``, which no configuration can override.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import timedelta
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .secret_types import Environment

MAX_CONFIG_BYTES = 16 * 1024


def _minutes(n: int) -> timedelta:
    return timedelta(minutes=n)


@dataclass(frozen=True)
class BrokerConfig:
    # --- TTLs (spec 5.2; PROPOSED defaults, tune with real task durations) ---
    default_ttl: timedelta = field(default_factory=lambda: _minutes(15))
    max_ttl: timedelta = field(default_factory=lambda: _minutes(30))  # MOCK and TEST
    max_ttl_real_credential: timedelta = field(
        default_factory=lambda: _minutes(60)
    )  # reserved, unused here
    # --- limits ---
    max_leases_per_task: int = 4
    max_uses_per_lease: int = 200
    sweep_interval: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    agent_rate_limit_per_minute: int = 30
    # PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL: spec 4.3(6) asks for a global limit without a number.
    global_rate_limit_per_minute: int = 300
    max_terminal_records: int = 1000
    # --- environments this process serves; PRODUCTION is rejected whatever is configured ---
    served_environments: frozenset = frozenset({Environment.MOCK})

    def __post_init__(self) -> None:
        for name in (
            "default_ttl",
            "max_ttl",
            "max_ttl_real_credential",
            "sweep_interval",
        ):
            value = getattr(self, name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise ConfigurationError(f"{name} must be a positive duration")
        for name in (
            "max_leases_per_task",
            "max_uses_per_lease",
            "agent_rate_limit_per_minute",
            "global_rate_limit_per_minute",
            "max_terminal_records",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer")
        if not self.default_ttl <= self.max_ttl <= self.max_ttl_real_credential:
            raise ConfigurationError(
                "require default_ttl <= max_ttl <= max_ttl_real_credential"
            )
        envs = self.served_environments
        if (
            not isinstance(envs, (set, frozenset))
            or not envs
            or not all(isinstance(e, Environment) for e in envs)
        ):
            raise ConfigurationError(
                "served_environments must be a non-empty set of Environment"
            )
        if Environment.PRODUCTION in envs:
            raise ConfigurationError("production can never be served to agents")
        object.__setattr__(self, "served_environments", frozenset(envs))

    # ---- loading ---------------------------------------------------------------------
    _SECONDS = {
        "default_ttl_seconds": "default_ttl",
        "max_ttl_seconds": "max_ttl",
        "max_ttl_real_credential_seconds": "max_ttl_real_credential",
        "sweep_interval_seconds": "sweep_interval",
    }
    _INTS = (
        "max_leases_per_task",
        "max_uses_per_lease",
        "agent_rate_limit_per_minute",
        "global_rate_limit_per_minute",
        "max_terminal_records",
    )

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> BrokerConfig:
        """Build from a plain mapping (e.g. parsed JSON). Unknown keys are rejected (fail closed)."""
        if not isinstance(mapping, Mapping):
            raise ConfigurationError("configuration must be a mapping")
        allowed = set(cls._SECONDS) | set(cls._INTS) | {"served_environments"}
        unknown = [k for k in mapping if k not in allowed]
        if unknown:
            raise ConfigurationError(
                "unknown configuration key"
            )  # key names are not echoed
        kwargs: dict = {}
        for key, attr in cls._SECONDS.items():
            if key in mapping:
                secs = mapping[key]
                if isinstance(secs, bool) or not isinstance(secs, (int, float)):
                    raise ConfigurationError(f"{key} must be a number")
                kwargs[attr] = timedelta(seconds=secs)
        for key in cls._INTS:
            if key in mapping:
                kwargs[key] = mapping[key]
        if "served_environments" in mapping:
            raw = mapping["served_environments"]
            if not isinstance(raw, (list, tuple, set, frozenset)):
                raise ConfigurationError("served_environments must be a list")
            envs = set()
            for item in raw:
                match = [
                    e for e in Environment if isinstance(item, str) and e.value == item
                ]
                if not match:
                    raise ConfigurationError(
                        "unknown environment in served_environments"
                    )
                envs.add(match[0])
            kwargs["served_environments"] = envs
        return cls(**kwargs)

    @classmethod
    def from_json_file(cls, path: Path) -> BrokerConfig:
        """Load from an explicitly given JSON file. Never searches paths or reads the environment."""
        data = None
        failed = False
        try:
            with open(path, "rb") as fh:
                data = fh.read(MAX_CONFIG_BYTES + 1)
            if len(data) > MAX_CONFIG_BYTES:
                failed = True
            else:
                doc = json.loads(data.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, RecursionError):
            failed = True
        if failed:
            raise ConfigurationError("configuration file unreadable or invalid")
        return cls.from_mapping(doc)

    def as_mapping(self) -> dict:
        """Plain-data view (seconds), e.g. for docs and tests."""
        out: dict = {}
        for key, attr in self._SECONDS.items():
            out[key] = getattr(self, attr).total_seconds()
        for key in self._INTS:
            out[key] = getattr(self, key)
        out["served_environments"] = sorted(e.value for e in self.served_environments)
        return out


CONFIG_FIELD_NAMES = tuple(f.name for f in fields(BrokerConfig))
