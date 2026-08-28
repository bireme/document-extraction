"""Tests del flujo desde PDFs con OCR cacheado (criterios C2-C6)"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.pdf_batch import run_batch_pdfs, transcribe_pdfs
from pdfsum.contract import SourceKind
from pdfsum.workspace import Workspace

_TEXT = (
    "RESUMO\nObjetivo: avaliar sarampo. Métodos: estudo. "
    "Resultados: dados. Conclusões: ok.\nPalavras-chave: saúde.\n"
    "ABSTRACT\nObjective: assess.\nKeywords: health.\n"
)


class CountingTranscriber:
    """Transcriber fake que cuenta invocaciones (para probar caché)."""

    def __init__(self, text):
        self.calls = 0
        self._text = text

    def transcribe(self, path):
        self.calls += 1
        return FakeTranscriber(
            self._text, pages=4, source_kind=SourceKind.NATIVO
        ).transcribe(path)


def _make_pdfs(d: Path, names):
    for n in names:
        (d / f"{n}.pdf").write_bytes(b"%PDF-1.4 fake")


class TestBatchPdf(unittest.TestCase):
    def test_batch_desde_pdf(self):
        """C2: procesa *.pdf -> ocr/ + summaries/ + report.json."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            ind.mkdir()
            _make_pdfs(ind, ["art"])
            ws = Workspace(Path(td) / "ws")
            report = run_batch_pdfs(
                str(ind), ws, FakeTranscriber(_TEXT, pages=4), FakeSummarizer()
            )
            self.assertTrue(ws.summary_path("art").exists())
            self.assertTrue(ws.report_path.exists())
            self.assertEqual(report["metrics"]["total"], 1)

    def test_ocr_cacheado(self):
        """C3: si ocr/<id>.txt existe, no se re-transcribe."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            ind.mkdir()
            _make_pdfs(ind, ["art"])
            ws = Workspace(Path(td) / "ws")
            tr = CountingTranscriber(_TEXT)
            transcribe_pdfs(str(ind), ws, tr)
            self.assertEqual(tr.calls, 1)
            transcribe_pdfs(str(ind), ws, tr)  # segunda vez: cacheado
            self.assertEqual(tr.calls, 1)  # no aumentó

    def test_ocr_persistido(self):
        """C4: existe ocr/<id>.txt con contenido tras el lote."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            ind.mkdir()
            _make_pdfs(ind, ["art"])
            ws = Workspace(Path(td) / "ws")
            transcribe_pdfs(str(ind), ws, FakeTranscriber(_TEXT, pages=4))
            ocr = ws.ocr_path("art")
            self.assertTrue(ocr.exists())
            self.assertIn("RESUMO", ocr.read_text(encoding="utf-8"))

    def test_report_origen(self):
        """C5: report incluye source_kind por documento."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            ind.mkdir()
            _make_pdfs(ind, ["art"])
            ws = Workspace(Path(td) / "ws")
            report = run_batch_pdfs(
                str(ind),
                ws,
                FakeTranscriber(_TEXT, pages=4, source_kind=SourceKind.NATIVO),
                FakeSummarizer(),
            )
            doc = report["documents"][0]
            self.assertEqual(doc["source_kind"], "nativo")
            self.assertEqual(
                json.loads(ws.summary_path("art").read_text())["meta"]["source_kind"],
                "nativo",
            )

    def test_report_em_logs_dir_separado(self):
        """C6: report.json é gravado em logs_dir separado do workspace."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            ind.mkdir()
            _make_pdfs(ind, ["art"])

            workspace_dir = Path(td) / "output"
            logs_dir = Path(td) / "logs"

            ws = Workspace(
                workspace_dir,
                logs_dir=logs_dir,
            )

            run_batch_pdfs(
                str(ind),
                ws,
                FakeTranscriber(_TEXT, pages=4),
                FakeSummarizer(),
            )

            self.assertTrue(
                (logs_dir / "report.json").exists()
            )

            self.assertFalse(
                (workspace_dir / "summaries" / "report.json").exists()
            )

            self.assertTrue(
                workspace_dir.joinpath(
                    "summaries", "art.json"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
