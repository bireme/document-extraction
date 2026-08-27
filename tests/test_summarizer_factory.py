"""Tests de adapters/summarizer_factory.py (criterio C4, FASE14)."""

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pdfsum.adapters.anthropic_summarizer import AnthropicSummarizer
from pdfsum.adapters.cloud_summarizer import CloudSummarizer
from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.ollama_summarizer import OllamaSummarizer
from pdfsum.adapters.summarizer_factory import (
    DEFAULT_MODEL_BY_BACKEND,
    build_summarizer,
    resolve_backend,
    resolve_model,
)


class TestResolveBackend(unittest.TestCase):
    def test_default_sin_flag_env_ni_config_es_ollama(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_backend(None), "ollama")

    def test_flag_cli_prevalece(self):
        with patch.dict("os.environ", {"PDFSUM_SUMMARIZER_BACKEND": "openai"}):
            self.assertEqual(resolve_backend("anthropic"), "anthropic")

    def test_env_var_si_no_hay_flag(self):
        with patch.dict("os.environ", {"PDFSUM_SUMMARIZER_BACKEND": "openrouter"}):
            self.assertEqual(resolve_backend(None), "openrouter")

    def test_backend_desconocido_lanza_valueerror(self):
        with self.assertRaises(ValueError):
            resolve_backend("acme-inexistente")


class TestResolveModel(unittest.TestCase):
    def test_flag_prevalece(self):
        self.assertEqual(resolve_model("ollama", "otro-modelo"), "otro-modelo")

    def test_default_por_backend_sin_config(self):
        import os
        from pathlib import Path

        with (
            TemporaryDirectory() as td,
            patch("pathlib.Path.home", return_value=Path(td)),
        ):
            cwd = os.getcwd()
            os.chdir(td)
            try:
                for backend, expected in DEFAULT_MODEL_BY_BACKEND.items():
                    self.assertEqual(resolve_model(backend, None), expected)
            finally:
                os.chdir(cwd)

    def test_openrouter_default_es_el_mismo_qwen_que_ollama_pero_hosted(self):
        # "los mismos modelos que tenemos, corriendo en la nube"
        self.assertIn("qwen", DEFAULT_MODEL_BY_BACKEND["openrouter"].lower())
        self.assertIn("2.5", DEFAULT_MODEL_BY_BACKEND["openrouter"])
        self.assertEqual(DEFAULT_MODEL_BY_BACKEND["ollama"], "qwen2.5:7b")


class TestBuildSummarizer(unittest.TestCase):
    def test_dry_run_siempre_fake_sin_importar_backend(self):
        s = build_summarizer("anthropic", "claude-haiku-4-5", dry_run=True)
        self.assertIsInstance(s, FakeSummarizer)

    def test_ollama(self):
        s = build_summarizer("ollama", "qwen2.5:7b")
        self.assertIsInstance(s, OllamaSummarizer)
        self.assertEqual(s.model, "qwen2.5:7b")

    def test_anthropic(self):
        s = build_summarizer("anthropic", "claude-haiku-4-5")
        self.assertIsInstance(s, AnthropicSummarizer)

    def test_openai_y_openrouter_usan_cloud_summarizer(self):
        s1 = build_summarizer("openai", "gpt-4o-mini")
        s2 = build_summarizer("openrouter", "qwen/qwen-2.5-7b-instruct")
        self.assertIsInstance(s1, CloudSummarizer)
        self.assertIsInstance(s2, CloudSummarizer)
        self.assertEqual(s1.provider, "openai")
        self.assertEqual(s2.provider, "openrouter")


if __name__ == "__main__":
    unittest.main()
