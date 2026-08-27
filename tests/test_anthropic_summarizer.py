"""Tests de adapters/anthropic_summarizer.py (criterio C3, FASE14).

Sin red real: mockea urllib.request.urlopen.
"""

import json
import unittest
from unittest.mock import patch

from pdfsum.adapters.anthropic_summarizer import AnthropicSummarizer
from pdfsum.contract import SummarizeRequest


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestAnthropicSummarizer(unittest.TestCase):
    def test_sin_api_key_lanza_runtime_error_accionable(self):
        with patch.dict("os.environ", {}, clear=True):
            s = AnthropicSummarizer(model="claude-haiku-4-5")
            with self.assertRaises(RuntimeError) as ctx:
                s._call("prompt")
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_api_key_desde_env_var(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            s = AnthropicSummarizer(model="claude-haiku-4-5")
        self.assertEqual(s.api_key, "sk-ant-test")

    def test_summarize_usa_esquema_messages_nativo_y_parsea_secciones(self):
        captured = {}

        def _urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["body"] = json.loads(req.data.decode("utf-8"))
            body = json.dumps(
                {"content": [{"type": "text", "text": "## Título\nMi título\n"}]}
            ).encode("utf-8")
            return _FakeResponse(body)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            s = AnthropicSummarizer(model="claude-haiku-4-5", api_key="sk-ant-test")
            req = SummarizeRequest(doc_id="d1", text="texto", lang="es", template="C")
            out = s.summarize(req)

        self.assertEqual(out["titulo"], "Mi título")
        self.assertEqual(captured["url"], "https://api.anthropic.com/v1/messages")
        # header nativo Anthropic: x-api-key + anthropic-version (NO Bearer)
        self.assertEqual(captured["headers"]["X-api-key"], "sk-ant-test")
        self.assertNotIn("Authorization", captured["headers"])
        self.assertEqual(captured["body"]["model"], "claude-haiku-4-5")


if __name__ == "__main__":
    unittest.main()
