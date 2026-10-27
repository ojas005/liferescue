"""Quick standalone launcher for LifeRescue application.
Run with: python apps/api/run.py
"""

import sys
from pathlib import Path

# Ensure repository root is in python path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from apps.api.config import get_settings  # noqa: E402

if __name__ == "__main__":
    settings = get_settings()
    print("=" * 65)
    print("  LifeRescue — AI Emergency Coordination & Readiness Platform")
    print(f"  AI Provider : {settings.ai_provider} (model {settings.nvidia_model if settings.ai_provider != 'mock' else 'deterministic mock'})")
    print(f"  Local Web UI: http://{settings.host}:{settings.port}")
    print(f"  API Docs    : http://{settings.host}:{settings.port}/docs")
    print("=" * 65)
    uvicorn.run(
        "apps.api.main:app", host=settings.host, port=settings.port, reload=False
    )
