"""Tests del transcriptor híbrido (criterios C4-C7)."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw

from pdfsum.adapters.fake_page_ocr import FakePageOCR
from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber


def _tsv(conf, words):
    lines = ["level\tpage_num\tconf\ttext"]
    for _ in range(words):
        lines.append(f"5\t1\t{conf}\tpalabra")
    return "\n".join(lines)


def _save_page_image(path: Path) -> None:
    """Imagen válida de 1 columna de texto (lo que pdftoppm produciría)."""
    img = Image.new("L", (400, 300), 255)
    d = ImageDraw.Draw(img)
    for y in range(20, 280, 20):
        d.rectangle([40, y, 360, y + 10], fill=0)
    img.save(path, "JPEG")


def _make_pdf(d: Path, name="x.pdf"):
    (d / name).write_bytes(b"%PDF-1.4 fake")


class TestHybridOcr(unittest.TestCase):
    def setUp(self):
        self.td = TemporaryDirectory()
        self.dir = Path(self.td.name)
        _make_pdf(self.dir)

    def tearDown(self):
        self.td.cleanup()

    def _hybrid(self, vlm):
        with patch("pdfsum.adapters.hybrid_ocr.shutil.which",
                   return_value="/usr/bin/x"):
            return HybridOcrTranscriber(lang="por", vlm=vlm)

    def test_usa_tesseract(self):
        """C4: alta confianza -> usa Tesseract y NO invoca el VLM."""
        vlm = FakePageOCR("texto vlm")
        with patch("pdfsum.adapters.hybrid_ocr.shutil.which",
                   return_value="/usr/bin/x"), \
             patch("pdfsum.adapters.hybrid_ocr._pdfinfo_pages", return_value=1), \
             patch("pdfsum.adapters.hybrid_ocr._run") as run:
            def fake_run(cmd, timeout=120):
                s = " ".join(cmd)
                if "pdftotext" in s:
                    return ""  # sin texto nativo -> escaneado
                if "tsv" in s:
                    return _tsv(95.0, 30)
                if "pdftoppm" in s:
                    _save_page_image(Path(cmd[-1] + "-1.jpg"))
                    return ""
                return "texto tesseract"
            run.side_effect = fake_run
            tr = self._hybrid(vlm).transcribe(str(self.dir / "x.pdf"))
        self.assertIn("texto tesseract", tr.text)
        self.assertEqual(vlm.calls, 0)

    def test_escala_vlm(self):
        """C5: baja confianza -> escala al VLM y usa su texto."""
        vlm = FakePageOCR("texto vlm")
        with patch("pdfsum.adapters.hybrid_ocr.shutil.which",
                   return_value="/usr/bin/x"), \
             patch("pdfsum.adapters.hybrid_ocr._pdfinfo_pages", return_value=1), \
             patch("pdfsum.adapters.hybrid_ocr._run") as run:
            def fake_run(cmd, timeout=120):
                s = " ".join(cmd)
                if "pdftotext" in s:
                    return ""
                if "tsv" in s:
                    return _tsv(40.0, 3)  # baja confianza
                if "pdftoppm" in s:
                    _save_page_image(Path(cmd[-1] + "-1.jpg"))
                    return ""
                return "texto tesseract"
            run.side_effect = fake_run
            tr = self._hybrid(vlm).transcribe(str(self.dir / "x.pdf"))
        self.assertIn("texto vlm", tr.text)
        self.assertGreaterEqual(vlm.calls, 1)

    def test_nativo_directo(self):
        """C6: PDF nativo -> pdftotext sin rasterizar ni OCR."""
        nativo = "texto largo del documento nativo " * 50
        with patch("pdfsum.adapters.hybrid_ocr.shutil.which",
                   return_value="/usr/bin/x"), \
             patch("pdfsum.adapters.hybrid_ocr._pdfinfo_pages", return_value=1), \
             patch("pdfsum.adapters.hybrid_ocr._run") as run:
            def fake_run(cmd, timeout=120):
                s = " ".join(cmd)
                if "pdftotext" in s:
                    return nativo
                return ""  # no debería rasterizar
            run.side_effect = fake_run
            tr = self._hybrid(FakePageOCR()).transcribe(str(self.dir / "x.pdf"))
        self.assertEqual(tr.text, nativo)
        self.assertEqual(tr.source_kind.value, "nativo")

    def test_lang_passthrough_tesseract(self):
        """C3 (FASE9): self.lang se pasa intacto a '-l' en tesseract, sin
        partir ni validar contra una lista fija (combo multi-idioma)."""
        lang_combo = "por+eng+spa+fra"
        seen_lang_args = []
        with patch("pdfsum.adapters.hybrid_ocr.shutil.which",
                   return_value="/usr/bin/x"), \
             patch("pdfsum.adapters.hybrid_ocr._pdfinfo_pages", return_value=1), \
             patch("pdfsum.adapters.hybrid_ocr._run") as run:
            def fake_run(cmd, timeout=120):
                s = " ".join(cmd)
                if "pdftotext" in s:
                    return ""  # sin texto nativo -> escaneado
                if cmd and cmd[0] == "tesseract" and "-l" in cmd:
                    seen_lang_args.append(cmd[cmd.index("-l") + 1])
                if "tsv" in s:
                    return _tsv(95.0, 30)
                if "pdftoppm" in s:
                    _save_page_image(Path(cmd[-1] + "-1.jpg"))
                    return ""
                return "texto tesseract"
            run.side_effect = fake_run
            with patch("pdfsum.adapters.hybrid_ocr.shutil.which",
                       return_value="/usr/bin/x"):
                tr = HybridOcrTranscriber(
                    lang=lang_combo, vlm=FakePageOCR()
                ).transcribe(str(self.dir / "x.pdf"))
        self.assertIn("texto tesseract", tr.text)
        self.assertTrue(seen_lang_args)
        self.assertTrue(all(l == lang_combo for l in seen_lang_args))

    def test_cli_run_hibrido_fake(self):
        """C7: run con fake no rompe (inyección del transcriptor)."""
        # La integración CLI->híbrido real se valida manualmente con Ollama;
        # aquí solo comprobamos que run acepta un transcriptor inyectado.
        from pdfsum.adapters.fake_summarizer import FakeSummarizer
        from pdfsum.adapters.fake_transcriber import FakeTranscriber
        from pdfsum.adapters.pdf_batch import run_batch_pdfs
        from pdfsum.workspace import Workspace
        ws = Workspace(self.dir / "ws")
        report = run_batch_pdfs(
            str(self.dir), ws, FakeTranscriber("texto", pages=1),
            FakeSummarizer())
        self.assertEqual(report["metrics"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
