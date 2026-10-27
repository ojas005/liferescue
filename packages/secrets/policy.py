"""Deny-by-default grant policy (KAN-45 spec section 4.3, step 2).

The policy file contains NAMES AND LIMITS ONLY, never values. Loading is strict and fails
closed: any problem raises ``PolicyError`` with a fixed message (no file content is echoed).

PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL: the spec suggests ``policy.yaml``; the
standard library has no YAML parser, so the policy is JSON (``policy.json``).

PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL: the grants in ``policy.json`` (agent ids and
mock secret names) are an illustrative mock-only set; Ojas approves real grant changes (spec Q6).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from .errors import PolicyError
from .secret_types import _ID_RE, _NAME_RE, Environment, Purpose, SecretRef

MAX_POLICY_BYTES = 64 * 1024
MAX_GRANTS = 200
MAX_NAMES_PER_GRANT = 50
MAX_NAME_SEGMENT = (
    16  # heuristic: a name segment longer than this looks like a value, not a name
)
MAX_GRANT_TTL_SECONDS = 24 * 3600
DEFAULT_POLICY_PATH = Path(__file__).with_name("policy.json")

_TOP_KEYS = {"version", "grants"}
_GRANT_KEYS = {"agent_id", "purpose", "names", "environments", "max_ttl_seconds"}


@dataclass(frozen=True)
class Grant:
    agent_id: str
    purpose: Purpose
    names: frozenset
    environments: frozenset
    max_ttl: timedelta | None = None


@dataclass(frozen=True)
class Policy:
    grants: tuple = ()
    version: int = 1

    def find_grant(self, agent_id: str, ref: SecretRef) -> Grant | None:
        """The grant covering (agent, purpose, name, environment), or None (deny by default)."""
        for grant in self.grants:
            if (
                grant.agent_id == agent_id
                and grant.purpose is ref.purpose
                and ref.name in grant.names
                and ref.environment in grant.environments
            ):
                return grant
        return None


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key")
        seen[key] = value
    return seen


def load_policy(path: Path | None = None) -> Policy:
    """Load and validate a policy file (default: the packaged ``policy.json``). Fail closed."""
    target = Path(path) if path is not None else DEFAULT_POLICY_PATH
    data: bytes | None = None
    failed = False
    try:
        with open(target, "rb") as fh:
            data = fh.read(MAX_POLICY_BYTES + 1)
    except OSError:
        failed = True
    if failed or data is None:
        raise PolicyError("policy file unreadable")
    return parse_policy(data)


def parse_policy(data) -> Policy:
    if isinstance(data, str):
        data = data.encode("utf-8", "strict")
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_POLICY_BYTES:
        raise PolicyError("policy too large or wrong type")
    doc: Any = None
    failed = False
    try:
        doc = json.loads(bytes(data).decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (ValueError, UnicodeDecodeError, RecursionError):
        failed = True
    if failed:
        raise PolicyError("policy is not valid JSON")
    return policy_from_mapping(doc)


def policy_from_mapping(doc: Any) -> Policy:
    if not isinstance(doc, Mapping) or set(doc) != _TOP_KEYS:
        raise PolicyError("policy top level must have exactly: version, grants")
    if doc["version"] != 1 or isinstance(doc["version"], bool):
        raise PolicyError("unsupported policy version")
    raw_grants = doc["grants"]
    if not isinstance(raw_grants, list) or len(raw_grants) > MAX_GRANTS:
        raise PolicyError("grants must be a list of bounded size")
    grants = []
    seen = set()
    for item in raw_grants:
        grant = _grant_from_mapping(item)
        key = (grant.agent_id, grant.purpose)
        if key in seen:
            # keep one grant per (agent, purpose): simpler to review than merged overlapping grants
            raise PolicyError("duplicate (agent_id, purpose) grant")
        seen.add(key)
        grants.append(grant)
    return Policy(grants=tuple(grants), version=1)


def _grant_from_mapping(item: Any) -> Grant:
    if (
        not isinstance(item, Mapping)
        or not set(item) <= _GRANT_KEYS
        or not {"agent_id", "purpose", "names", "environments"} <= set(item)
    ):
        raise PolicyError("grant has missing or unknown fields")
    agent_id = item["agent_id"]
    if not isinstance(agent_id, str) or not _ID_RE.match(agent_id):
        raise PolicyError("grant agent_id invalid")
    purpose = _enum_or_none(Purpose, item["purpose"])
    if purpose is None:
        raise PolicyError("grant purpose unknown")
    names = item["names"]
    if not isinstance(names, list) or not names or len(names) > MAX_NAMES_PER_GRANT:
        raise PolicyError("grant names must be a non-empty bounded list")
    for name in names:
        _check_secret_name(name)
    envs_raw = item["environments"]
    if not isinstance(envs_raw, list) or not envs_raw:
        raise PolicyError("grant environments must be a non-empty list")
    envs = set()
    for env_s in envs_raw:
        env = _enum_or_none(Environment, env_s)
        if env is None:
            raise PolicyError("grant environment unknown")
        if env is Environment.PRODUCTION:
            # T-14: a policy that tries to grant PRODUCTION is invalid; startup fails closed.
            raise PolicyError("production cannot be granted")
        envs.add(env)
    max_ttl = None
    if "max_ttl_seconds" in item:
        secs = item["max_ttl_seconds"]
        if (
            isinstance(secs, bool)
            or not isinstance(secs, int)
            or not 0 < secs <= MAX_GRANT_TTL_SECONDS
        ):
            raise PolicyError("grant max_ttl_seconds invalid")
        max_ttl = timedelta(seconds=secs)
    return Grant(agent_id, purpose, frozenset(names), frozenset(envs), max_ttl)


def _check_secret_name(name: Any) -> None:
    """Names must look like names. This also rejects value-shaped strings (T-26, defence in depth)."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise PolicyError("grant name invalid")
    if any(len(seg) > MAX_NAME_SEGMENT for seg in re.split(r"[-_]", name)):
        raise PolicyError("grant name looks like a value")
    if sum(ch.isdigit() for ch in name) > 8:
        raise PolicyError("grant name looks like a value")


def _enum_or_none(enum_cls, value):
    if not isinstance(value, str):
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    return None
