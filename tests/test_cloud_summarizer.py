"""Tests de adapters/cloud_summarizer.py (criterios C3, C7, FASE14).

Sin red real: mockea urllib.request.urlopen (mismo patrón usado ya en
test_doctor.py/test_preconditions.py para _ollama_models).
"""

import json
import unittest
from unittest.mock import patch

from pdfsum.adapters.cloud_summarizer import CloudSummarizer
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


def _openai_style_response(text: str) -> _FakeResponse:
    body = json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")
    return _FakeResponse(body)


class TestCloudSummarizer(unittest.TestCase):
    def test_provider_desconocido_sin_base_url(self):
        with self.assertRaises(ValueError):
            CloudSummarizer(provider="acme", model="x")

    def test_base_url_custom_permite_cualquier_gateway(self):
        s = CloudSummarizer(
            provider="acme", model="x", base_url="http://localhost:9999/v1"
        )
        self.assertEqual(s.base_url, "http://localhost:9999/v1")

    def test_sin_api_key_lanza_runtime_error_accionable(self):
        with patch.dict("os.environ", {}, clear=True):
            s = CloudSummarizer(provider="openai", model="gpt-4o-mini")
            with self.assertRaises(RuntimeError) as ctx:
                s._call("prompt")
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_api_key_desde_env_var_por_proveedor(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-test"}):
            s = CloudSummarizer(
                provider="openrouter", model="qwen/qwen-2.5-7b-instruct"
            )
        self.assertEqual(s.api_key, "sk-or-test")

    def test_summarize_llama_endpoint_correcto_y_parsea_secciones(self):
        captured = {}

        def _urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _openai_style_response("## Título\nMi título\n")

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            s = CloudSummarizer(
                provider="openai", model="gpt-4o-mini", api_key="sk-test"
            )
            req = SummarizeRequest(doc_id="d1", text="texto", lang="es", template="C")
            out = s.summarize(req)

        self.assertEqual(out["titulo"], "Mi título")
        self.assertEqual(captured["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(captured["body"]["model"], "gpt-4o-mini")
        self.assertIn("texto", captured["body"]["messages"][0]["content"])

    def test_timeout_y_error_externo_se_propagan(self):
        """La red no puede convertir una falla externa en una respuesta vacía."""
        summarizer = CloudSummarizer(
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-test",
            timeout=23,
        )
        for error in (TimeoutError("demora"), OSError("red no disponible")):
            with (
                self.subTest(error=type(error).__name__),
                patch("urllib.request.urlopen", side_effect=error) as urlopen,
                self.assertRaises(type(error)),
            ):
                summarizer._call("prompt")
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 23)

    def test_payload_invalido_no_se_acepta_como_respuesta(self):
        """JSON corrupto o sin el contrato esperado produce un error visible."""
        summarizer = CloudSummarizer(
            provider="openai", model="gpt-4o-mini", api_key="sk-test"
        )
        cases = (
            (_FakeResponse(b"{"), json.JSONDecodeError),
            (_FakeResponse(b'{"choices": []}'), IndexError),
        )
        for response, error_type in cases:
            with (
                self.subTest(error=error_type.__name__),
                patch("urllib.request.urlopen", return_value=response),
                self.assertRaises(error_type),
            ):
                summarizer._call("prompt")

    def test_respuesta_vacia_se_conserva_vacia(self):
        """Un contenido vacío válido no se sustituye por texto inventado."""
        response = _openai_style_response("")
        with patch("urllib.request.urlopen", return_value=response):
            output = CloudSummarizer(
                provider="openai", model="gpt-4o-mini", api_key="sk-test"
            )._call("prompt")
        self.assertEqual(output, "")

    def test_no_leak_api_key_en_mensaje_error(self):
        """C7: la API key no aparece en el mensaje de error (solo el nombre de la env var)."""
        with patch.dict("os.environ", {}, clear=True):
            s = CloudSummarizer(provider="openai", model="gpt-4o-mini", api_key="")
            with self.assertRaises(RuntimeError) as ctx:
                s._call("prompt")
        msg = str(ctx.exception)
        self.assertIn("OPENAI_API_KEY", msg)
        self.assertNotIn("Authorization", msg)
        self.assertNotIn("Bearer", msg)


if __name__ == "__main__":
    unittest.main()
