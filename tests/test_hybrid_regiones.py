"""FASE18 C7: marcador de región no textual (sin VLM disponible)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from pdfsum.adapters.hybrid_ocr import NON_TEXT_MARKER


def _make_transcriber(vlm=None):
    from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber

    with patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/bin/x"):
        return HybridOcrTranscriber(lang="spa", vlm=vlm)


def _page_with_figure(td: Path) -> Path:
    """Página con un bloque denso de tinta (figura) sin texto."""
    img = Image.new("L", (800, 1000), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 100, 700, 900], fill=30)  # figura maciza
    p = td / "page.pgm"
    img.save(p, format="PPM")
    return p


class _FakeVlm:
    def __init__(self):
        self.calls = 0

    def ocr_image(self, path, lang):
        self.calls += 1
        return "texto recuperado por el vlm"


class TestRegionNoTextual(unittest.TestCase):
    def _ocr(self, transcriber, img):
        # OCR pobre simulado: 2 palabras con confianza 20.
        with patch.object(
            transcriber,
            "_ocr_page",
            return_value=(
                "xx zz",
                20.0,
                2,
                {"vlm": False, "vlm_rejected": False, "motivo": None},
            ),
        ):
            metrics = {}
            text = transcriber._ocr_regions(img, metrics)
        return text, metrics

    def test_sin_vlm_marca_region(self):
        with tempfile.TemporaryDirectory() as td:
            img = _page_with_figure(Path(td))
            tx = _make_transcriber(vlm=None)
            text, metrics = self._ocr(tx, img)
            self.assertIn(NON_TEXT_MARKER, text)
            self.assertNotIn("xx zz", text)
            self.assertGreaterEqual(metrics["non_text_regions"], 1)

    def test_con_vlm_flujo_actual_intacto(self):
        """Con VLM el routing existente decide; no se marca nada."""
        with tempfile.TemporaryDirectory() as td:
            img = _page_with_figure(Path(td))
            tx = _make_transcriber(vlm=_FakeVlm())
            text, metrics = self._ocr(tx, img)
            self.assertNotIn(NON_TEXT_MARKER, text)
            self.assertEqual(metrics["non_text_regions"], 0)

    def test_texto_legible_no_se_marca(self):
        """OCR con palabras/conf normales no dispara el marcador."""
        with tempfile.TemporaryDirectory() as td:
            img = _page_with_figure(Path(td))
            tx = _make_transcriber(vlm=None)
            with patch.object(
                tx,
                "_ocr_page",
                return_value=(
                    "texto normal de la región",
                    85.0,
                    30,
                    {"vlm": False, "vlm_rejected": False, "motivo": None},
                ),
            ):
                metrics = {}
                text = tx._ocr_regions(img, metrics)
            self.assertNotIn(NON_TEXT_MARKER, text)
            self.assertIn("texto normal", text)


if __name__ == "__main__":
    unittest.main()
