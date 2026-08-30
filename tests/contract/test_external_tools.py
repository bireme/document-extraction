"""Interacciones reales mínimas con poppler, Tesseract y Ollama."""

import os
import shutil
import subprocess
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont

from pdfsum.adapters.ollama_summarizer import OllamaSummarizer
from pdfsum.adapters.vlm_ocr import VlmPageOCR
from pdfsum.contract import PageOCR, Summarizer
from tests.fixtures.pdf_factory import write_native_pdf


class TestPopplerContract(unittest.TestCase):
    def setUp(self):
        missing = [tool for tool in ("pdfinfo", "pdftoppm") if not shutil.which(tool)]
        if missing:
            self.skipTest(f"dependencia opcional ausente: {', '.join(missing)}")

    def test_pdfinfo_y_pdftoppm_procesan_pdf_controlado(self):
        """Poppler informa una página y genera una imagen válida."""
        with TemporaryDirectory() as td:
            directory = Path(td)
            pdf = write_native_pdf(directory / "nativo.pdf", ["CONTRATO PDFSUM"])
            info = subprocess.run(
                ["pdfinfo", str(pdf)],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            self.assertIn("Pages:", info.stdout)
            self.assertRegex(info.stdout, r"(?m)^Pages:\s+1$")
            prefix = directory / "pagina"
            subprocess.run(
                ["pdftoppm", "-png", "-singlefile", str(pdf), str(prefix)],
                capture_output=True,
                check=True,
                timeout=20,
            )
            image_path = directory / "pagina.png"
            self.assertTrue(image_path.exists())
            with Image.open(image_path) as image:
                image.verify()


class TestTesseractContract(unittest.TestCase):
    def setUp(self):
        if not shutil.which("tesseract"):
            self.skipTest("dependencia opcional ausente: tesseract")

    def test_tesseract_reconoce_texto_simple(self):
        """Tesseract devuelve contenido de una imagen local controlada."""
        with TemporaryDirectory() as td:
            image_path = Path(td) / "texto.png"
            image = Image.new("L", (900, 180), 255)
            draw = ImageDraw.Draw(image)
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", 54)
            except OSError:
                font = ImageFont.load_default()
            draw.text((30, 45), "CONTRACT TEST PDFSUM", fill=0, font=font)
            image.save(image_path)
            result = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "7"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            normalized = result.stdout.upper().replace(" ", "")
            self.assertIn("PDFSUM", normalized)


class TestOllamaContract(unittest.TestCase):
    def setUp(self):
        if not shutil.which("ollama"):
            self.skipTest("dependencia opcional ausente: ollama")
        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1).close()
        except (OSError, urllib.error.URLError):
            self.skipTest("servicio opcional no disponible: Ollama local")

    def test_adapter_summarizer_cumple_puerto(self):
        self.assertIsInstance(OllamaSummarizer(), Summarizer)

    def test_vlm_cumple_puerto(self):
        self.assertIsInstance(VlmPageOCR(), PageOCR)

    def test_modelo_real_minimo_si_fue_configurado(self):
        """Ejecuta inferencia real solo con un modelo opt-in ya instalado."""
        model = os.getenv("PDFSUM_CONTRACT_OLLAMA_MODEL")
        if not model:
            self.skipTest("define PDFSUM_CONTRACT_OLLAMA_MODEL para inferencia real")
        result = subprocess.run(
            ["ollama", "run", model, "Responde solamente OK"],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        self.assertTrue(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
