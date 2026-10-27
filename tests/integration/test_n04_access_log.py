"""LR 08 N-04: token redaction must not break uvicorn's access log line (real server, real formatter)."""

import io
import logging
import socket
import threading
import time
import unittest
import urllib.request

import uvicorn
from uvicorn.logging import AccessFormatter

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

TOKEN = "demo-tok-N04-" + "q7Zp3xLm"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestN04AccessLog(unittest.TestCase):
    def test_access_line_emitted_and_token_redacted(self):
        reset_for_tests(":memory:")
        app = create_app(
            Settings(db_path=":memory:", ai_provider="mock", demo_access_token=TOKEN)
        )
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            AccessFormatter(
                '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
            )
        )
        access = logging.getLogger("uvicorn.access")
        access.addHandler(handler)
        access.setLevel(logging.INFO)
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_config=None, access_log=True
            )
        )
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.05)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(
                f"http://127.0.0.1:{port}/health?leak={TOKEN}", timeout=5
            ) as r:
                self.assertEqual(r.status, 200)
            time.sleep(0.2)
        finally:
            server.should_exit = True
            t.join(5)
            access.removeHandler(handler)
            for f in list(access.filters):
                access.removeFilter(f)
            for f in list(logging.getLogger().filters):
                logging.getLogger().removeFilter(f)
            for f in list(logging.getLogger("liferescue").filters):
                logging.getLogger("liferescue").removeFilter(f)
        out = stream.getvalue()
        self.assertIn("GET /health?leak=[REDACTED:demo_token]", out)
        self.assertIn("200", out)
        self.assertNotIn(TOKEN, out)


if __name__ == "__main__":
    unittest.main()
