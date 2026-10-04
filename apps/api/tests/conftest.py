"""Test bootstrap: make `app` (apps/api) and `contract` (packages/contract) importable without
installing anything, and keep every test hermetic (no real keys, no real network)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
for p in (API_ROOT, REPO_ROOT / "packages" / "contract", Path(__file__).parent / "runtime"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if os.environ.get("LIFERESCUE_CONTRACT_PATH"):
    sys.path.insert(0, os.environ["LIFERESCUE_CONTRACT_PATH"])


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch):
    from app.runtime.redaction import clear_registered_secrets

    for name in (
        "NEBIUS_API_KEY",
        "TAVILY_API_KEY",
        "NEBIUS_BASE_URL",
        "NEBIUS_MODEL",
        "AI_PROVIDER",
        "LIFERESCUE_MODEL_ADAPTER",
        "LIFERESCUE_ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    clear_registered_secrets()
    yield
    clear_registered_secrets()
