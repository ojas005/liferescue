"""LR 08 SEC-10 (Medium): key only sent over https (localhost excepted); response size capped."""

import json
import unittest
from datetime import datetime, timezone

import httpx

from packages.domain.ai import MAX_PROVIDER_RESPONSE_BYTES, NVIDIAAIProvider
from packages.domain.models import Incident

KEY = "fake-sec10-key-not-real"


def _incident():
    return Incident(user_id="usr_demo", title="t", description="My chest hurts", created_at=datetime.now(timezone.utc))


class TestSec10(unittest.TestCase):
    def _provider(self, base_url, body=None):
        self.calls = []

        def handler(request):
            self.calls.append(request)
            return httpx.Response(200, content=body or b"{}")

        return NVIDIAAIProvider(api_key=KEY, base_url=base_url, transport=httpx.MockTransport(handler))

    def test_http_base_url_refused_and_key_not_sent(self):
        for url in ("http://attacker.invalid/v1", "ftp://x/v1", "file:///etc", "nonsense"):
            with self.subTest(url=url):
                p = self._provider(url)
                a = p.analyze_emergency(_incident())
                self.assertEqual(self.calls, [])
                self.assertIn("insecure_base_url", a.provider_name)

    def test_https_and_localhost_allowed(self):
        for url in ("https://api.tokenfactory.nebius.com/v1/", "http://127.0.0.1:9999/v1", "http://localhost/v1"):
            with self.subTest(url=url):
                p = self._provider(url)
                p.analyze_emergency(_incident())
                self.assertEqual(len(self.calls), 1)
                self.assertTrue(self.calls[0].headers["authorization"].endswith(KEY))

    def test_oversized_response_falls_back(self):
        filler = "x" * (MAX_PROVIDER_RESPONSE_BYTES + 10)
        body = json.dumps({"choices": [{"message": {"content": filler}}]}).encode()
        a = self._provider("https://api.tokenfactory.nebius.com/v1/", body).analyze_emergency(_incident())
        self.assertIn("response_too_large", a.provider_name)


if __name__ == "__main__":
    unittest.main()
