#!/usr/bin/env python3
"""Generate apps/api/openapi.json from the app (no DB connection is made).

python scripts/export_openapi.py          # rewrite openapi.json
python scripts/export_openapi.py --check  # exit 1 if the checked-in file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
OUT = API_DIR / "openapi.json"
sys.path.insert(0, str(API_DIR))


def render() -> str:
    from app.main import create_app
    from app.settings import Settings

    settings = Settings(_env_file=None, liferescue_env="test", model_adapter="mock", database_url="sqlite://")
    schema = create_app(settings).openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("openapi.json is stale: run `python scripts/export_openapi.py`", file=sys.stderr)
            return 1
        print("openapi.json is up to date")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
