"""One-command LIVE smoke test for the Nebius provider (KAN-38/KAN-39).

    python apps/api/scripts/smoke_nebius.py

Needs env NEBIUS_API_KEY (never printed, never read from a file by this script). Optional:
NEBIUS_BASE_URL, NEBIUS_MODEL. Without a key it prints "key not provided" and exits 0 so it is safe
in CI and on machines without credentials. Exit codes: 0 = ok or key not provided, 1 = live call failed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from _bootstrap import setup

setup()

from contract.models import Message  # noqa: E402
from pydantic import BaseModel, ConfigDict  # noqa: E402

from app.runtime.errors import NotConfigured  # noqa: E402
from app.runtime.model_gateway import NebiusProvider  # noqa: E402
from app.runtime.redaction import redact_text  # noqa: E402


class SmokeReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    echo: str


async def main() -> int:
    provider = NebiusProvider()
    print(f"provider=nebius model={provider.model_id} base_url={provider.base_url}")
    if not provider.is_configured():
        print("key not provided: set NEBIUS_API_KEY to run the live smoke test (skipping, exit 0)")
        return 0
    try:
        health = await provider.health_check()
        print(f"health_check: ok={health.ok} latency_ms={health.latency_ms} detail={health.detail}")
        res = await provider.complete_structured(
            SmokeReply,
            [Message(role="user", content='Reply with JSON: {"ok": true, "echo": "pong"}')],
            purpose="smoke",
            max_tokens=128,
            timeout_s=float(os.environ.get("NEBIUS_TIMEOUT_S", "30")),
        )
    except NotConfigured:
        print("key not provided")
        return 0
    except Exception as exc:  # report, never leak
        print(f"LIVE CALL FAILED: {type(exc).__name__}: {redact_text(str(exc))[:300]}")
        return 1
    print("LIVE CALL OK")
    print(
        json.dumps(
            {
                "model": res.model,
                "adapter": res.adapter,
                "output": res.output.model_dump(),
                "usage": res.usage.model_dump(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
