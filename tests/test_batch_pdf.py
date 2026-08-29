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


class SelectiveTranscriber:
    def transcribe(self, path):
        if Path(path).stem == "bad":
            raise RuntimeError("fallo simulado de OCR")
        return FakeTranscriber(
            _TEXT, pages=4, source_kind=SourceKind.NATIVO
        ).transcribe(path)


class EventTranscriber:
    """Transcriptor fake que emite progreso mediante el destino inyectado."""

    def __init__(self):
        self.sink = None

    def set_event_sink(self, sink):
        previous = self.sink
        self.sink = sink
        return previous

    def transcribe(self, path):
        self.sink(
            "ocr_pagina_completada",
            doc_id=Path(path).stem,
            pagina=1,
            paginas_total=1,
        )
        return FakeTranscriber(
            _TEXT, pages=1, source_kind=SourceKind.ESCANEADO
        ).transcribe(path)


class InterruptingSummarizer:
    def summarize(self, request):
        if request.doc_id == "b":
            raise KeyboardInterrupt()
        return FakeSummarizer().summarize(request)


def _make_pdfs(d: Path, names):
    for n in names:
        (d / f"{n}.pdf").write_bytes(b"%PDF-1.4 fake")


class TestBatchPdf(unittest.TestCase):
    def test_c02_batch_desde_pdf(self):
        """C02: procesa *.pdf -> ocr/ + summaries/ + report.json."""
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
            self.assertEqual(report["duration_unit"], "seconds")
            self.assertIn("gpu_monitoring", report["infrastructure"])
            self.assertIn("tiempo_medio_por_fase", report["metrics"])
            self.assertIn("transcripcion", report["documents"][0]["tiempos_por_fase"])
            self.assertIn("resumen", report["documents"][0]["tiempos_por_fase"])

    def test_c03_ocr_cacheado(self):
        """C03: si ocr/<id>.txt existe, no se re-transcribe."""
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

    def test_c04_ocr_persistido(self):
        """C04: existe ocr/<id>.txt con contenido tras el lote."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            ind.mkdir()
            _make_pdfs(ind, ["art"])
            ws = Workspace(Path(td) / "ws")
            transcribe_pdfs(str(ind), ws, FakeTranscriber(_TEXT, pages=4))
            ocr = ws.ocr_path("art")
            self.assertTrue(ocr.exists())
            self.assertIn("RESUMO", ocr.read_text(encoding="utf-8"))

    def test_c05_report_origen(self):
        """C05: report incluye source_kind por documento."""
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

    def test_c06_report_en_logs_dir_separado(self):
        """C06: report.json se escribe en logs_dir separado del workspace."""
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

    def test_progreso_ocr_llega_al_log_durable(self):
        """El lote conecta y restaura el destino de eventos del transcriptor."""
        with TemporaryDirectory() as td:
            input_dir = Path(td) / "entrada"
            input_dir.mkdir()
            _make_pdfs(input_dir, ["art"])
            logs_dir = Path(td) / "logs"
            workspace = Workspace(Path(td) / "salida", logs_dir=logs_dir)
            transcriber = EventTranscriber()

            run_batch_pdfs(
                str(input_dir), workspace, transcriber, FakeSummarizer()
            )

            events = (logs_dir / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event":"ocr_pagina_completada"', events)
            self.assertIn('"pagina":1', events)
            self.assertIsNone(transcriber.sink)

    def test_log_continuo_y_fallo_aislado(self):
        """El fallo de un PDF queda registrado y el lote continúa con el próximo."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            ind.mkdir()
            _make_pdfs(ind, ["bad", "good"])
            logs = Path(td) / "logs"
            ws = Workspace(Path(td) / "ws", logs_dir=logs)

            report = run_batch_pdfs(
                str(ind), ws, SelectiveTranscriber(), FakeSummarizer()
            )

            self.assertEqual(report["status"], "completed_with_errors")
            self.assertEqual(report["progress"]["completed"], 1)
            self.assertEqual(report["progress"]["failed"], 1)
            statuses = {doc["doc_id"]: doc["status"] for doc in report["documents"]}
            self.assertEqual(statuses, {"bad": "failed", "good": "completed"})
            events = (logs / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event":"document_failed"', events)
            self.assertIn('"event":"document_completed"', events)
            self.assertTrue((logs / "infrastructure.jsonl").exists())
            self.assertGreaterEqual(report["infrastructure"]["sample_count"], 2)

    def test_checkpoint_sobrevive_interrupcion(self):
        """Una interrupción preserva en el reporte los documentos ya terminados."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            ind.mkdir()
            _make_pdfs(ind, ["a", "b"])
            logs = Path(td) / "logs"
            ws = Workspace(Path(td) / "ws", logs_dir=logs)

            with self.assertRaises(KeyboardInterrupt):
                run_batch_pdfs(
                    str(ind),
                    ws,
                    FakeTranscriber(_TEXT, pages=4),
                    InterruptingSummarizer(),
                )

            report = json.loads((logs / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "interrupted")
            self.assertEqual(report["progress"]["completed"], 1)
            self.assertEqual(report["documents"][0]["doc_id"], "a")
            events = (logs / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event":"run_interrupted"', events)


if __name__ == "__main__":
    unittest.main()
