"""FASE19 C4: rechazo VLM visible en meta, eventos, gate y report."""

import json
import tempfile
import unittest
from pathlib import Path

from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.pdf_batch import run_batch_pdfs
from pdfsum.contract import SourceKind
from pdfsum.workspace import Workspace

_TEXTO = (
    "A saúde pública é uma disciplina que estuda a saúde da população "
    "para proteger e melhorar o bem-estar das pessoas em geral. "
) * 10


class _TranscriberConRechazo(FakeTranscriber):
    """Fake que respeta el contrato del híbrido: sink + evento de rechazo."""

    def __init__(self):
        super().__init__(
            _TEXTO,
            pages=2,
            source_kind=SourceKind.ESCANEADO,
            pages_detail=[
                {
                    "page": 1,
                    "source": "tesseract",
                    "conf": 85.0,
                    "words": 200,
                    "chars": 900,
                },
                {
                    "page": 2,
                    "source": "tesseract",
                    "conf": 42.0,
                    "words": 30,
                    "chars": 150,
                    "vlm_rejected": True,
                    "vlm_motivo": "solape lexico 0.10 < 0.3",
                },
            ],
        )
        self._sink = None

    def set_event_sink(self, sink):
        previous = self._sink
        self._sink = sink
        return previous

    def transcribe(self, path):
        if self._sink is not None:
            self._sink(
                "vlm_rechazado",
                doc_id=Path(path).stem,
                pagina=2,
                motivo="solape lexico 0.10 < 0.3",
            )
        return super().transcribe(path)


class TestBatchVlmVerify(unittest.TestCase):
    def test_rechazo_visible_en_meta_evento_gate_y_report(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            in_dir = base / "in"
            in_dir.mkdir()
            (in_dir / "doc1.pdf").write_bytes(b"%PDF-fake-1")
            ws = Workspace(str(base / "ws"))

            report = run_batch_pdfs(
                str(in_dir), ws, _TranscriberConRechazo(), FakeSummarizer()
            )

            # meta.json con el contador de rechazos
            meta = json.loads(
                (ws.ocr_dir / "doc1.meta.json").read_text(encoding="utf-8")
            )
            self.assertEqual(meta["quality"]["paginas_vlm_rechazado"], 1)

            # evento en events.jsonl
            events_file = ws.report_path.parent / "events.jsonl"
            eventos = [
                json.loads(line)
                for line in events_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            rechazos = [e for e in eventos if e["event"] == "vlm_rechazado"]
            self.assertEqual(len(rechazos), 1)
            self.assertEqual(rechazos[0]["pagina"], 2)

            # gate warning en _qa.transcript
            record = json.loads(ws.summary_path("doc1").read_text(encoding="utf-8"))
            gates = {
                f["gate"]: f["severity"]
                for f in record["_qa"]["transcript"]["failures"]
            }
            self.assertEqual(gates.get("vlm_rechazado"), "warning")
            self.assertTrue(record["_qa"]["transcript"]["passed"])  # warning

            # visible en report 3.1
            doc = report["documents"][0]
            self.assertIn("vlm_rechazado", doc["transcription_quality"]["gates"])


if __name__ == "__main__":
    unittest.main()
