import importlib.util
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]


def test_checked_in_openapi_json_has_no_drift() -> None:
    """If this fails: `python scripts/export_openapi.py` and commit apps/api/openapi.json."""
    spec = importlib.util.spec_from_file_location("export_openapi", API_DIR / "scripts" / "export_openapi.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (API_DIR / "openapi.json").read_text() == mod.render()
