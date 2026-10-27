"""KAN-50 P1 (f): no misleading UI claims; MOCK vs LIVE mode visible; audit append-only is true."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

STATIC = Path(__file__).resolve().parents[2] / "apps" / "api" / "static"


class TestUiClaims(unittest.TestCase):
    def test_no_misleading_claims(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        for bad in ("LIVE EMERGENCY DISPATCH", "&lt; 150ms", "FIRST_AID_GUIDANCE", "SCENE_SAFETY", "Immutable", "immutable"):
            with self.subTest(bad=bad):
                self.assertNotIn(bad, html + js)
        self.assertIn("NO REAL DISPATCH", html)

    def test_mode_labels_present(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        for label in ("AI Engine: LIVE", "AI Engine: MOCK fallback", "AI Engine: MOCK (", "mock_fallback", "'LIVE'"):
            with self.subTest(label=label):
                self.assertIn(label, js)

    def test_health_reports_mock_mode(self):
        reset_for_tests(":memory:")
        c = TestClient(create_app(Settings(db_path=":memory:", ai_provider="mock")))
        self.assertEqual(c.get("/health").json()["ai_mode"], "mock")


class TestAuditAppendOnly(unittest.TestCase):
    def test_db_rejects_update_and_delete(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "a.db")
            reset_for_tests(path)
            c = TestClient(create_app(Settings(db_path=path, ai_provider="mock")))
            c.post("/demo/scenarios/scenario_medical/run")
            c.post("/demo/reset")
            conn = sqlite3.connect(path)
            try:
                n = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
                self.assertGreater(n, 0)
                for stmt in ("DELETE FROM audit_events", "UPDATE audit_events SET result='x'"):
                    with self.subTest(stmt=stmt), self.assertRaises(sqlite3.DatabaseError):
                        conn.execute(stmt)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], n)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
