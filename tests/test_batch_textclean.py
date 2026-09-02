"""FASE17 C5: limpieza en memoria en run_batch_pdfs; ocr/*.txt queda crudo."""

import json
import tempfile
import unittest
from pathlib import Path

from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.pdf_batch import run_batch_pdfs
from pdfsum.workspace import Workspace

# Transcript crudo: hifenización + encabezado repetido en 4 páginas.
_PAGINA = (
    "Rev. Salud Pública {n}\n"
    "La vigilancia epidemiológica permite obtener informa-\n"
    "ción oportuna sobre los eventos de salud de la población {n}.\n"
    "{n}\n"
)
_CRUDO = "\f".join(_PAGINA.format(n=n) for n in range(1, 5))


class TestLimpiezaEnMemoria(unittest.TestCase):
    def test_txt_crudo_y_resumen_sobre_limpio(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            in_dir = base / "in"
            in_dir.mkdir()
            (in_dir / "doc1.pdf").write_bytes(b"%PDF-fake-1")
            ws = Workspace(str(base / "ws"))

            run_batch_pdfs(
                str(in_dir),
                ws,
                FakeTranscriber(_CRUDO, pages=4),
                FakeSummarizer(),
            )

            # el transcript persistido es CRUDO (auditable)
            raw = ws.ocr_path("doc1").read_text(encoding="utf-8")
            self.assertIn("informa-\n", raw)
            self.assertIn("Rev. Salud Pública 2", raw)

            # el resumen se computó sobre el texto limpio
            record = json.loads(ws.summary_path("doc1").read_text(encoding="utf-8"))
            meta = record["meta"]
            self.assertTrue(meta["text_cleaned"])
            self.assertEqual(meta["chars_crudo"], len(_CRUDO))
            self.assertLess(meta["chars_limpio"], meta["chars_crudo"])
            # text_chars del pipeline refleja el texto limpio
            self.assertEqual(meta["text_chars"], meta["chars_limpio"])


if __name__ == "__main__":
    unittest.main()
