"""FASE16 C5: gate de transcript integrado en run_batch_pdfs + report 3.1."""

import json
import tempfile
import unittest
from pathlib import Path

from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.pdf_batch import run_batch_pdfs
from pdfsum.workspace import Workspace

_TEXTO = (
    "A saúde pública é uma disciplina que estuda a saúde da população "
    "para proteger e melhorar o bem-estar das pessoas em geral. "
) * 10


class TestBatchTranscriptQA(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        base = Path(self._td.name)
        self.in_dir = base / "in"
        self.in_dir.mkdir()
        (self.in_dir / "doc1.pdf").write_bytes(b"%PDF-fake-1")
        self.ws = Workspace(str(base / "ws"))

    def tearDown(self):
        self._td.cleanup()

    def _run(self, text=_TEXTO, pages_detail=None):
        return run_batch_pdfs(
            str(self.in_dir),
            self.ws,
            FakeTranscriber(text, pages=1, pages_detail=pages_detail),
            FakeSummarizer(),
        )

    def test_registro_lleva_qa_transcript(self):
        self._run()
        record = json.loads(self.ws.summary_path("doc1").read_text(encoding="utf-8"))
        self.assertIn("transcript", record["_qa"])
        self.assertTrue(record["_qa"]["transcript"]["passed"])
        # el QA del resumen conserva su forma previa (aditivo)
        self.assertIn("passed", record["_qa"])
        self.assertIn("failures", record["_qa"])

    def test_report_31_aditivo_con_transcription_quality(self):
        report = self._run(
            pages_detail=[
                {
                    "page": 1,
                    "source": "tesseract",
                    "conf": 88.0,
                    "words": 100,
                    "chars": len(_TEXTO),
                },
            ]
        )
        self.assertEqual(report["report_version"], "3.1")
        tq = report["transcription_quality"]
        self.assertEqual(tq["docs_evaluados"], 1)
        self.assertEqual(tq["docs_con_error"], 0)
        self.assertEqual(tq["conf_media"], 88.0)
        # campos 3.0 intactos (contrato observabilidad PR #6)
        for key in (
            "run_id",
            "status",
            "progress",
            "metrics",
            "infrastructure",
            "documents",
        ):
            self.assertIn(key, report)
        doc = report["documents"][0]
        self.assertIn("transcription_quality", doc)
        self.assertTrue(doc["transcription_quality"]["passed"])
        self.assertIn("qa_ok", doc)  # campo 3.0 preservado

    def test_transcript_degradado_marcado_pero_no_bloquea(self):
        """Decisión validada por el PO: error de transcript NO omite el
        resumen; queda marcado en _qa, documents y agregado."""
        basura = ("₪≈₩ ▓▒░ ø∏∑ ☒☒ ∫∂µ ¥₽ " * 40).strip()
        report = self._run(text=basura)
        doc = report["documents"][0]
        self.assertEqual(doc["status"], "completed")  # se resumió igual
        self.assertFalse(doc["transcription_quality"]["passed"])
        self.assertIn("garbage", doc["transcription_quality"]["gates"])
        self.assertEqual(report["transcription_quality"]["docs_con_error"], 1)
        record = json.loads(self.ws.summary_path("doc1").read_text(encoding="utf-8"))
        self.assertFalse(record["_qa"]["transcript"]["passed"])

    def test_events_incluye_transcript_qa_completed(self):
        self._run()
        events_file = self.ws.report_path.parent / "events.jsonl"
        eventos = [
            json.loads(line)["event"]
            for line in events_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertIn("transcript_qa_completed", eventos)


if __name__ == "__main__":
    unittest.main()
