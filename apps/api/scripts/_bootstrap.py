"""Path bootstrap for the dev scripts (no install needed). Dev tooling only."""

from __future__ import annotations

import os
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]


def setup() -> None:
    paths = [API_ROOT, REPO_ROOT / "packages" / "contract", API_ROOT / "tests" / "runtime"]
    if os.environ.get("LIFERESCUE_CONTRACT_PATH"):
        paths.insert(0, Path(os.environ["LIFERESCUE_CONTRACT_PATH"]))
    for p in paths:
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
