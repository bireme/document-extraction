"""FASE20 C2: upload crea job idempotente."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pdfsum.adapters.api_service import create_app

_PDF = b"%PDF-1.4\n%fake\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


class TestApiService(unittest.TestCase):
    def test_upload_crea_job_y_es_idempotente(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            app = create_app(ws, token="t")
            c = TestClient(app)
            headers = {"Authorization": "Bearer t"}

            r1 = c.post(
                "/api/documents",
                headers=headers,
                files={"file": ("a.pdf", _PDF, "application/pdf")},
            )
            self.assertEqual(r1.status_code, 202)
            job1 = r1.json()["job_id"]

            r2 = c.post(
                "/api/documents",
                headers=headers,
                files={"file": ("b.pdf", _PDF, "application/pdf")},
            )
            self.assertEqual(r2.status_code, 202)
            self.assertEqual(r2.json()["job_id"], job1)

            # solo un job persistido
            jobs = list((ws / "service_jobs").glob("*.json"))
            self.assertEqual(len(jobs), 1)
            # inbox escrito
            inbox = list((ws / "inbox").rglob("*.pdf"))
            self.assertEqual(len(inbox), 1)
