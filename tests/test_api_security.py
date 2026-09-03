"""FASE20 C4: seguridad por punto (token, tamaño, magic bytes)."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pdfsum.adapters.api_service import create_app


class TestApiSecurity(unittest.TestCase):
    def test_no_token_no_arranca(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(ValueError):
            create_app(Path(td) / "ws", token="")

    def test_401_sin_token(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td) / "ws", token="t")
            c = TestClient(app)
            r = c.get("/api/health")
            self.assertEqual(r.status_code, 401)

    def test_401_token_invalido(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td) / "ws", token="t")
            c = TestClient(app)
            r = c.get("/api/health", headers={"Authorization": "Bearer x"})
            self.assertEqual(r.status_code, 401)

    def test_health_ok_con_token(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td) / "ws", token="t")
            c = TestClient(app)
            r = c.get("/api/health", headers={"Authorization": "Bearer t"})
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body["status"], "ok")
            self.assertIn("version", body)
            self.assertIn("ocr_pipeline_version", body)
            self.assertNotIn("PDFSUM_API_TOKEN", str(body))

    def test_upload_limite_tamano_413(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td) / "ws", token="t", max_upload_mb=0)
            c = TestClient(app)
            r = c.post(
                "/api/documents",
                headers={"Authorization": "Bearer t"},
                files={"file": ("a.pdf", b"%PDF-1" + b"x", "application/pdf")},
            )
            self.assertEqual(r.status_code, 413)

    def test_magic_bytes_415(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td) / "ws", token="t")
            c = TestClient(app)
            r = c.post(
                "/api/documents",
                headers={"Authorization": "Bearer t"},
                files={"file": ("a.pdf", b"NOTPDF", "application/pdf")},
            )
            self.assertEqual(r.status_code, 415)
