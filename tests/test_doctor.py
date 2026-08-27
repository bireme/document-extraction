"""Tests del verificador de entorno (criterios C3, C4; C6 de FASE14)."""

import unittest
from unittest.mock import patch

from pdfsum.adapters.doctor import (
    Check,
    capabilities,
    check_environment,
    environment_ok,
    summarization_ready,
)


class TestDoctor(unittest.TestCase):
    def test_check_environment(self):
        """C3: devuelve checks {name,ok,detail,hard} sin lanzar."""
        checks = check_environment()
        self.assertTrue(checks)
        names = {c.name for c in checks}
        # requisitos duros de poppler presentes en la lista
        self.assertIn("pdftotext", names)
        self.assertIn("pdfinfo", names)
        self.assertIn("pdftoppm", names)
        for c in checks:
            self.assertIsInstance(c.ok, bool)
            self.assertIsInstance(c.detail, str)

    def test_environment_ok(self):
        """C4: environment_ok True solo si los requisitos duros están."""
        all_hard_ok = [
            Check("pdftotext", True, "", hard=True),
            Check("tesseract", False, "", hard=False),  # opcional falla
        ]
        self.assertTrue(environment_ok(all_hard_ok))
        one_hard_missing = [
            Check("pdftotext", False, "", hard=True),
            Check("pdfinfo", True, "", hard=True),
        ]
        self.assertFalse(environment_ok(one_hard_missing))


class TestDoctorBackendCloud(unittest.TestCase):
    """FASE14 C6: doctor/summarization_ready son backend-aware."""

    def test_check_environment_cloud_sin_key(self):
        with patch.dict("os.environ", {}, clear=True):
            checks = check_environment(text_model="gpt-4o-mini", backend="openai")
        by = {c.name: c for c in checks}
        self.assertIn("openai_api_key", by)
        self.assertFalse(by["openai_api_key"].ok)
        self.assertIn("OPENAI_API_KEY", by["openai_api_key"].detail)
        # ollama sigue reportado (informativo, para el fallback VLM de OCR)
        self.assertIn("ollama", by)

    def test_check_environment_cloud_con_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            checks = check_environment(
                text_model="claude-haiku-4-5", backend="anthropic"
            )
        by = {c.name: c for c in checks}
        self.assertTrue(by["anthropic_api_key"].ok)

    def test_capabilities_resumen_true_con_api_key_sin_ollama(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            checks = check_environment(text_model="gpt-4o-mini", backend="openai")
        caps = capabilities(checks)
        self.assertTrue(caps["resumen"])

    def test_summarization_ready_cloud_sin_key(self):
        with patch.dict("os.environ", {}, clear=True):
            ok, msg = summarization_ready("gpt-4o-mini", backend="openai")
        self.assertFalse(ok)
        self.assertIn("OPENAI_API_KEY", msg)

    def test_summarization_ready_cloud_con_key(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            ok, msg = summarization_ready(
                "qwen/qwen-2.5-7b-instruct", backend="openrouter"
            )
        self.assertTrue(ok)
        self.assertIn("openrouter", msg)


if __name__ == "__main__":
    unittest.main()
