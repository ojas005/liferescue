"""LR 08 N-03: explicit api_key never falls back to env; tests see no provider key."""

import os
import unittest

from packages.domain.ai import NVIDIAAIProvider


class TestN03Isolation(unittest.TestCase):
    def test_explicit_empty_api_key_does_not_read_env(self):
        old = os.environ.get("NEBIUS_API_KEY")
        os.environ["NEBIUS_API_KEY"] = "env-should-not-be-used"
        try:
            self.assertEqual(NVIDIAAIProvider(api_key="").api_key, "")
            self.assertEqual(NVIDIAAIProvider(api_key="explicit").api_key, "explicit")
        finally:
            if old is None:
                os.environ.pop("NEBIUS_API_KEY", None)
            else:
                os.environ["NEBIUS_API_KEY"] = old

    def test_omitted_api_key_reads_env(self):
        os.environ["NVIDIA_API_KEY"] = "from-env"
        try:
            self.assertEqual(NVIDIAAIProvider().api_key, "from-env")
        finally:
            os.environ.pop("NVIDIA_API_KEY", None)
