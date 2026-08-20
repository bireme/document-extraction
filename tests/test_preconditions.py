"""Tests de precondiciones y capacidades (criterios C1-C5)."""
import io
import unittest
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pdfsum.adapters.doctor import Check, capabilities, summarization_ready
from pdfsum.cli import main


def _checks(ollama=True, text_model=True, vlm=True, tess=True):
    cs = [
        Check("pdftotext", True, "", hard=True),
        Check("pdfinfo", True, "", hard=True),
        Check("pdftoppm", True, "", hard=True),
        Check("tesseract", tess, "", hard=False),
    ]
    if ollama:
        cs.append(Check("ollama", True, "", hard=False))
        cs.append(Check("model:qwen2.5:7b", text_model, "", hard=False))
        cs.append(Check("model:qwen3-vl:8b-instruct", vlm, "", hard=False))
    else:
        cs.append(Check("ollama", False, "", hard=False))
    return cs


class TestPreconditions(unittest.TestCase):
    def test_capabilities(self):
        """C1: capacidades booleanas por dependencias presentes."""
        caps = capabilities(_checks())
        self.assertTrue(caps["extraer_nativo"])
        self.assertTrue(caps["ocr_imagen"])
        self.assertTrue(caps["resumen"])
        self.assertTrue(caps["ocr_vlm"])
        # sin ollama -> sin resumen ni vlm
        caps2 = capabilities(_checks(ollama=False))
        self.assertTrue(caps2["extraer_nativo"])
        self.assertFalse(caps2["resumen"])
        self.assertFalse(caps2["ocr_vlm"])

    def test_preflight_ok(self):
        """C2: modelo presente -> (True, msg)."""
        with patch("pdfsum.adapters.doctor._ollama_models",
                   return_value=["qwen2.5:7b", "otro"]):
            ok, msg = summarization_ready("qwen2.5:7b")
        self.assertTrue(ok)
        self.assertIn("disponibles", msg)

    def test_preflight_falta(self):
        """C3: ollama caído o modelo ausente -> (False, msg accionable)."""
        with patch("pdfsum.adapters.doctor._ollama_models", return_value=None):
            ok, msg = summarization_ready("qwen2.5:7b")
        self.assertFalse(ok)
        self.assertIn("ollama pull", msg)
        self.assertIn("INSTALL.md", msg)
        # ollama arriba pero sin el modelo
        with patch("pdfsum.adapters.doctor._ollama_models",
                   return_value=["otro:1b"]):
            ok2, msg2 = summarization_ready("qwen2.5:7b")
        self.assertFalse(ok2)
        self.assertIn("falta el modelo", msg2)

    def test_cli_precondicion(self):
        """C4: 'run' sin ollama/modelo -> mensaje claro, código != 0."""
        with TemporaryDirectory() as td, \
                patch("pdfsum.adapters.doctor._ollama_models",
                      return_value=None):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["run", "--in", td, "--workspace", td])
            self.assertNotEqual(rc, 0)
            self.assertIn("Precondición no cumplida", buf.getvalue())

    def test_doctor_capacidades(self):
        """C5: 'doctor' imprime el bloque de capacidades."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["doctor"])
        self.assertIn("Capacidades disponibles", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
