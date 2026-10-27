"""KAN-50 P1: NVIDIAAIProvider (Nemotron on Nebius Token Factory) with fake HTTP, no network."""

import json
import logging
import unittest

import httpx

from apps.api.config import Settings
from packages.domain.ai import (
    DEFAULT_NEBIUS_BASE_URL,
    DEFAULT_NEMOTRON_MODEL,
    NVIDIAAIProvider,
    create_ai_provider,
    extract_json_object,
)
from packages.domain.models import Incident, UrgencyLevel
from packages.domain.safety_policy import SafetyPolicyEngine

FAKE_KEY = "fake-test-key-not-a-secret-0001"
GOOD = {
    "summary": "Possible cardiac event",
    "category": "medical",
    "urgency": "critical",
    "severity_score": 9,
    "confidence": 0.9,
    "immediate_threat": True,
    "extracted_facts": {"symptom": "chest pain"},
    "missing_critical_info": ["Is the patient conscious?"],
    "recommended_immediate_steps": ["Call 112 now."],
}


def _incident():
    return Incident(
        title="Chest pain", description="Crushing chest pain, struggling to breathe"
    )


def _provider(handler):
    return NVIDIAAIProvider(
        api_key=FAKE_KEY, transport=httpx.MockTransport(handler), timeout_s=2
    )


def _reply(content, status=200):
    def handler(request):
        return httpx.Response(
            status, json={"choices": [{"message": {"content": content}}]}
        )

    return handler


class TestNvidiaProvider(unittest.TestCase):
    def test_defaults_are_nebius_and_nemotron(self):
        p = NVIDIAAIProvider(api_key=FAKE_KEY)
        self.assertEqual(p.base_url, DEFAULT_NEBIUS_BASE_URL)
        self.assertTrue(p.model.startswith("nvidia/nemotron"))
        self.assertEqual(DEFAULT_NEMOTRON_MODEL, "nvidia/nemotron-3-super-120b-a12b")

    def test_settings_drive_factory(self):
        s = Settings(
            ai_provider="nebius",
            nebius_api_key=FAKE_KEY,
            nvidia_model="nvidia/x",
            ai_timeout_s=5,
        )
        p = create_ai_provider("nebius", s)
        self.assertIsInstance(p, NVIDIAAIProvider)
        self.assertEqual((p.api_key, p.model, p.timeout_s), (FAKE_KEY, "nvidia/x", 5.0))

    def test_success_request_shape_and_validation(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(GOOD)}}]}
            )

        a = _provider(handler).analyze_emergency(_incident())
        self.assertEqual(
            seen["url"], "https://api.tokenfactory.nebius.com/v1/chat/completions"
        )
        self.assertEqual(seen["auth"], f"Bearer {FAKE_KEY}")
        self.assertEqual(seen["body"]["response_format"], {"type": "json_object"})
        self.assertEqual(a.urgency, UrgencyLevel.CRITICAL)
        self.assertIn("nvidia_ai", a.provider_name)
        self.assertNotIn("mock_fallback", a.provider_name)

    def test_fenced_json_and_think_block(self):
        content = "<think>reasoning</think>\n```json\n" + json.dumps(GOOD) + "\n```"
        a = _provider(_reply(content)).analyze_emergency(_incident())
        self.assertNotIn("mock_fallback", a.provider_name)
        self.assertEqual(extract_json_object('```\n{"a": 1}\n```'), {"a": 1})

    def _assert_fallback(self, provider, reason):
        a = provider.analyze_emergency(_incident())
        self.assertIn("mock_fallback", a.provider_name)
        self.assertIn(reason, a.provider_name)
        self.assertTrue(provider.last_status.startswith("fallback"))
        return a

    def test_malformed_json_falls_back_labelled(self):
        self._assert_fallback(_provider(_reply("not json at all")), "invalid_response")

    def test_schema_violation_falls_back_labelled(self):
        bad = dict(GOOD, severity_score=99)
        self._assert_fallback(_provider(_reply(json.dumps(bad))), "invalid_response")
        bad2 = dict(GOOD, urgency="apocalyptic")
        self._assert_fallback(_provider(_reply(json.dumps(bad2))), "invalid_response")

    def test_timeout_falls_back_labelled(self):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        self._assert_fallback(_provider(handler), "timeout")

    def test_401_and_5xx_fall_back_labelled(self):
        self._assert_fallback(_provider(_reply("{}", 401)), "http_401")
        self._assert_fallback(_provider(_reply("{}", 503)), "http_503")

    def test_not_configured_is_labelled(self):
        p = NVIDIAAIProvider(api_key=None)
        p.api_key = None
        self._assert_fallback(p, "not_configured")

    def test_key_never_logged(self):
        with self.assertLogs("liferescue.ai", level="INFO") as cm:
            _provider(_reply("{}", 500)).analyze_emergency(_incident())
            logging.getLogger("liferescue.ai").info("marker")
        self.assertNotIn(FAKE_KEY, "\n".join(cm.output))

    def test_live_output_still_vetted_by_safety_policy(self):
        """A live reply that under-rates chest pain is still escalated by the deterministic policy."""
        under = dict(GOOD, urgency="low", severity_score=2, immediate_threat=False)
        inc = _incident()
        a = _provider(_reply(json.dumps(under))).analyze_emergency(inc)
        self.assertNotIn("mock_fallback", a.provider_name)
        risk = SafetyPolicyEngine().evaluate_risk(inc, a)
        self.assertTrue(risk.requires_escalation)
        self.assertIn(risk.urgency, (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL))


if __name__ == "__main__":
    unittest.main()
