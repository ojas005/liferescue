#!/usr/bin/env python3
"""One harmless live call to NVIDIA Nemotron on Nebius Token Factory (KAN-50).

Usage:  NEBIUS_API_KEY=... python scripts/smoke_nvidia.py      (or put the key in .env)
Prints provider, model id, base URL, latency, schema validation and the deterministic
policy decision. Never prints the key, the prompt or the raw model reply.
Exit codes: 0 live call validated, 2 no key configured, 3 live call failed (labelled fallback).
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from apps.api.config import get_settings  # noqa: E402
from packages.domain.ai import NVIDIAAIProvider, create_ai_provider  # noqa: E402
from packages.domain.models import Incident  # noqa: E402
from packages.domain.safety_policy import SafetyPolicyEngine  # noqa: E402

SMOKE_INCIDENT = Incident(
    title="Smoke test (synthetic, not a real emergency)",
    description="Synthetic test: an adult reports sudden chest pain and shortness of breath.",
    location="Test location",
)


def main() -> int:
    settings = get_settings()
    provider = create_ai_provider("nebius", settings)
    assert isinstance(provider, NVIDIAAIProvider)
    print("provider     : nvidia_ai via Nebius Token Factory")
    print(f"model        : {provider.model}")
    print(f"base_url     : {provider.base_url}")
    print(f"key present  : {provider.is_live_configured()} (value never printed)")
    if not provider.is_live_configured():
        print("result       : NOT RUN - set NEBIUS_API_KEY in the environment or .env")
        return 2
    t0 = time.perf_counter()
    analysis = provider.analyze_emergency(SMOKE_INCIDENT)
    latency_ms = round((time.perf_counter() - t0) * 1000)
    live = "mock_fallback" not in analysis.provider_name
    risk = SafetyPolicyEngine().evaluate_risk(SMOKE_INCIDENT, analysis)
    print(f"latency_ms   : {latency_ms}")
    print(f"provider_name: {analysis.provider_name}")
    print(f"validation   : {'ok (AIAnalysis schema)' if live else 'FAILED -> ' + provider.last_status}")
    print(f"model urgency: {analysis.urgency.value} severity={analysis.severity_score}")
    print(f"policy       : urgency={risk.urgency.value} escalate={risk.requires_escalation} rule={risk.policy_rule_triggered}")
    print(f"result       : {'LIVE OK' if live else 'FALLBACK (live call failed)'}")
    return 0 if live else 3


if __name__ == "__main__":
    sys.exit(main())
