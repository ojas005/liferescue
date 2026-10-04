"""PLACEHOLDER identity (contract assumption: no auth in the sprint, single owner ``demo-user``).

PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL: the caller may send ``X-Actor-Id`` and it is recorded as
``decided_by`` / ``requested_by``; absent or malformed -> ``demo-user``. This is NOT authentication (any client can
claim any id). SECURITY-REQUIREMENTS A2/A3 (auth, per-user run ownership/IDOR) are therefore NOT covered yet.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header

ACTOR_HEADER = "X-Actor-Id"
DEFAULT_ACTOR = "demo-user"
_ACTOR_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}$")


def parse_actor(value: str | None) -> str:
    return value if value is not None and _ACTOR_RE.fullmatch(value) else DEFAULT_ACTOR


def current_actor(x_actor_id: Annotated[str | None, Header(alias=ACTOR_HEADER)] = None) -> str:
    return parse_actor(x_actor_id)
