"""FASE20 C3/C5: worker procesa la cola y preserva checkpoint en interrupción."""

import json
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from pdfsum.adapters.api_service import create_app
from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.job_store import DirJobStore
from pdfsum.adapters.service_worker import run_once

_PDF = b"%PDF-1.4\n%fake\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


class _InterruptingTranscriber(FakeTranscriber):
    def transcribe(self, path):
        raise KeyboardInterrupt("simulado")


@unittest.skipIf(
    TestClient is None,
    "FastAPI no instalado: instala el extra opcional pdfsum[service]",
)
class TestWorker(unittest.TestCase):
    def _enqueue(self, ws: Path) -> str:
        app = create_app(ws, token="t")
        c = TestClient(app)
        r = c.post(
            "/api/documents",
            headers={"Authorization": "Bearer t"},
            files={"file": ("a.pdf", _PDF, "application/pdf")},
        )
        self.assertEqual(r.status_code, 202)
        return r.json()["job_id"]

    def test_worker_produce_artefactos(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            job_id = self._enqueue(ws)

            n = run_once(ws, FakeTranscriber("texto", pages=1), FakeSummarizer())
            self.assertEqual(n, 1)

            # job pasa a done
            store = DirJobStore(ws / "service_jobs")
            job = store.get(job_id)
            self.assertEqual(job["state"], "done")

            # artefactos principales
            doc_id = job["doc_id"]
            self.assertTrue((ws / "summaries" / f"{doc_id}.json").exists())
            self.assertTrue((ws / "ocr" / f"{doc_id}.txt").exists())
            self.assertTrue((ws / "ocr" / f"{doc_id}.meta.json").exists())

            # endpoint jobs refleja done
            app = create_app(ws, token="t")
            c = TestClient(app)
            st = c.get(
                f"/api/jobs/{job_id}",
                headers={"Authorization": "Bearer t"},
            ).json()
            self.assertEqual(st["status"], "done")
            self.assertIn("summary_url", st)

    def test_interrupcion_preserva_checkpoint_y_reintenta(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            job_id = self._enqueue(ws)

            with self.assertRaises(KeyboardInterrupt):
                run_once(ws, _InterruptingTranscriber("x"), FakeSummarizer())

            # report del job debe existir con status interrupted
            jobs_dir = ws / "jobs"
            reports = list(jobs_dir.rglob("report.json"))
            self.assertTrue(reports)
            rep = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(rep["status"], "interrupted")

            # job marcado failed
            store = DirJobStore(ws / "service_jobs")
            job = store.get(job_id)
            self.assertEqual(job["state"], "failed")

            # segundo intento completa
            run_once(ws, FakeTranscriber("texto", pages=1), FakeSummarizer())
            job = store.get(job_id)
            self.assertEqual(job["state"], "done")
