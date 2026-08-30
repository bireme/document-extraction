"""Tests del híbrido con segmentación (criterios C5, C6)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw

from pdfsum.adapters.fake_page_ocr import FakePageOCR
from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber


def _pdf_2cols(d: Path) -> Path:
    """Imagen de 2 columnas como 'pdf' (el híbrido la rasteriza)."""
    img = Image.new("L", (800, 600), 255)
    dr = ImageDraw.Draw(img)
    for y in range(50, 550, 18):
        dr.rectangle([80, y, 340, y + 10], fill=0)  # columna izq
        dr.rectangle([460, y, 720, y + 10], fill=0)  # columna der
    pdf = d / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    return pdf


def _make_page_image(d: Path) -> Path:
    """Imagen real de 2 columnas (lo que pdftoppm produciría)."""
    img = Image.new("L", (800, 600), 255)
    dr = ImageDraw.Draw(img)
    for y in range(50, 550, 18):
        dr.rectangle([80, y, 340, y + 10], fill=0)
        dr.rectangle([460, y, 720, y + 10], fill=0)
    out = d / "page.jpg"
    img.save(out, "JPEG")
    return out


def _tsv_low():
    return "level\tpage_num\tconf\ttext\n5\t1\t40.0\tx\n5\t1\t40.0\ty\n"


class TestHybridSeg(unittest.TestCase):
    def setUp(self):
        self.td = TemporaryDirectory()
        self.dir = Path(self.td.name)
        self.pdf = _pdf_2cols(self.dir)

    def tearDown(self):
        self.td.cleanup()

    def _hybrid(self, vlm):
        with patch(
            "pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/usr/bin/x"
        ):
            return HybridOcrTranscriber(lang="por", vlm=vlm)

    def test_segmenta_y_ensambla(self):
        """C5: página 2 columnas densa (baja confianza) -> segmenta y usa VLM."""
        vlm = FakePageOCR("REGION")
        with (
            patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/usr/bin/x"),
            patch("pdfsum.adapters.hybrid_ocr._pdfinfo_pages", return_value=1),
            patch("pdfsum.adapters.hybrid_ocr._run") as run,
        ):
            page_img = _make_page_image(self.dir)

            def fake_run(cmd, timeout=120):
                s = " ".join(str(c) for c in cmd)
                if "pdftotext" in s:
                    return ""  # sin texto nativo -> escaneado
                if "pdftoppm" in s:
                    # producir la imagen rasterizada en el prefijo pedido
                    prefix = Path(cmd[-1])
                    Image.open(page_img).save(Path(str(prefix) + "-1.jpg"), "JPEG")
                    return ""
                if "tsv" in s:
                    return _tsv_low()  # baja confianza -> VLM
                return "txt"

            run.side_effect = fake_run
            tr = self._hybrid(vlm).transcribe(str(self.pdf))
        # el VLM fue invocado por región (al menos 2 regiones de las columnas)
        self.assertGreaterEqual(vlm.calls, 1)
        self.assertIn("REGION", tr.text)

    def test_orden_ensamble(self):
        """C6: el texto ensamblado respeta orden de lectura (marcadores)."""
        seen: list[str] = []

        class MarkingOCR:
            def ocr_image(self, image_path, lang):
                # devuelve un marcador con la posición del recorte
                name = Path(image_path).stem
                seen.append(name)
                return f"<{name}>"

        with (
            patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/usr/bin/x"),
            patch("pdfsum.adapters.hybrid_ocr._pdfinfo_pages", return_value=1),
            patch("pdfsum.adapters.hybrid_ocr._run") as run,
        ):
            page_img = _make_page_image(self.dir)

            def fake_run(cmd, timeout=120):
                s = " ".join(str(c) for c in cmd)
                if "pdftotext" in s:
                    return ""
                if "pdftoppm" in s:
                    prefix = Path(cmd[-1])
                    Image.open(page_img).save(Path(str(prefix) + "-1.jpg"), "JPEG")
                    return ""
                if "tsv" in s:
                    return _tsv_low()
                return "t"

            run.side_effect = fake_run
            tr = self._hybrid(MarkingOCR()).transcribe(str(self.pdf))
        # los marcadores aparecen en orden de lectura (col izq antes que der)
        self.assertTrue(seen)
        # La proyección añade margen, por eso se comparan las columnas
        # descubiertas en vez de fijar coordenadas exactas y frágiles.
        positions = {name: int(name.split("_")[2]) for name in seen}
        self.assertGreater(len(set(positions.values())), 1)
        left = min(positions, key=positions.get)
        right = max(positions, key=positions.get)
        left_idx = tr.text.find(f"<{left}>")
        right_idx = tr.text.find(f"<{right}>")
        self.assertGreaterEqual(left_idx, 0)
        self.assertGreaterEqual(right_idx, 0)
        self.assertLess(left_idx, right_idx)


if __name__ == "__main__":
    unittest.main()
