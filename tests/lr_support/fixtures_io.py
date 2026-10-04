"""Load the synthetic fixtures in tests/fixtures. Fixtures are data; nothing here talks to a network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load_json(rel: str) -> Any:
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def golden_cases(file_name: str) -> list[dict[str, Any]]:
    return load_json(f"golden/{file_name}")["cases"]


def fake_secret_cases() -> list[dict[str, Any]]:
    return load_json("redaction/fake_secrets.json")["cases"]
