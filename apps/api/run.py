"""Quick standalone launcher for LifeRescue application.
Run with: python apps/api/run.py
"""

import sys
from pathlib import Path

# Ensure repository root is in python path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from apps.api.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    from apps.api.access import TUNNEL_WARNING, InsecureBindError, enforce_bind_policy

    try:
        enforce_bind_policy(
            settings.host, settings.demo_access_token, settings.demo_require_token
        )
    except InsecureBindError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    print("=" * 65)
    print("  LifeRescue — AI Emergency Coordination & Readiness Platform")
    print(
        f"  AI Provider : {settings.ai_provider} (model {settings.nvidia_model if settings.ai_provider != 'mock' else 'deterministic mock'})"
    )
    print(f"  Local Web UI: http://{settings.host}:{settings.port}")
    print(f"  API Docs    : http://{settings.host}:{settings.port}/docs")
    print(
        f"  Access gate : {'X-Demo-Token required' if settings.demo_access_token else 'open (localhost only)'}"
    )
    print("=" * 65)
    if not settings.demo_access_token:
        print(TUNNEL_WARNING, file=sys.stderr)
    uvicorn.run(
        "apps.api.main:app", host=settings.host, port=settings.port, reload=False
    )
