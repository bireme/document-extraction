"""Contrato HTTP, aislamiento y reutilización del pipeline sin servicios externos."""

import builtins
import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from pdfsum import cli
from pdfsum.adapters import abstract_api
from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.pdf_download import DownloadError, PDFDownloader
from pdfsum.workspace import Workspace


@unittest.skipIf(TestClient is None, "Instala el extra opcional pdfsum[service]")
class TestAbstractAPI(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "workspace"
        self.logs = self.base / "logs"
        self.download = Mock()
        self.download.download.side_effect = lambda url, path: path.write_bytes(
            b"%PDF-1.4\n%%EOF\n"
        )
        self.processor = Mock(side_effect=self.process)
        self.app = abstract_api.create_app(
            self.root,
            processor=self.processor,
            logs_dir=self.logs,
            downloader=self.download,
        )
        self.client = TestClient(self.app)
        self.payload = {
            "id": 79665,
            "url": "https://public.example/doc.pdf?token=secreto",
        }

    def process(self, pdf, ws):
        ws.ocr_dir.mkdir()
        ws.ocr_path(pdf.stem).write_text("contenido sensible")
        return {
            "doc_id": pdf.stem,
            "status": "found",
            "source_kind": "nativo",
            "abstracts": [
                {
                    "lang": "es",
                    "header": "Resumen",
                    "text": "Texto original",
                    "keywords": "",
                }
            ],
        }

    def post(self, **changes):
        return self.client.post(
            "/api/extract-abstracts", json={**self.payload, **changes}
        )

    def test_success_preserves_result_identity_and_cleans(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], 79665)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["result"]["abstracts"][0]["text"], "Texto original")
        self.assertFalse(list(self.root.iterdir()))
        logs = "".join(p.read_text() for p in self.logs.rglob("*.jsonl"))
        self.assertNotIn("secreto", logs)
        self.assertNotIn("contenido sensible", logs)
        self.assertIn("request_completed", logs)

    def test_string_identity_never_used_as_path(self):
        identity = "../../identidad externa"
        response = self.post(id=identity)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], identity)
        pdf = self.processor.call_args.args[0]
        self.assertNotIn("identidad", str(pdf))

    def test_invalid_identity(self):
        for identity in [
            None,
            True,
            False,
            0,
            -1,
            3.2,
            "",
            " ",
            "x" * 257,
            "a\nb",
            [],
            {},
        ]:
            with self.subTest(identity=identity):
                response = self.post(id=identity)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["id"], identity)
                self.assertEqual(response.json()["phase"], "validation")
        self.download.download.assert_not_called()

    def test_invalid_url(self):
        for url in [
            None,
            [],
            4,
            "no-url",
            "ftp://example.org/doc",
            "http://user:secret@example.org/doc",
            "http://localhost/a",
            "http://10.0.0.1/a",
            "http://[::1]/a",
            "http://example.org:99999/a",
            "http://example.org/a\nb",
        ]:
            with self.subTest(url=url):
                response = self.post(url=url)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["id"], 79665)
                self.assertNotIn("secret", response.text)
        self.download.download.assert_not_called()

    def test_malformed_missing_and_extra_fields(self):
        for body in [
            {"id": 79665},
            {"url": "https://example.org/a"},
            {**self.payload, "backend": "fake"},
            [],
            None,
        ]:
            with self.subTest(body=body):
                response = self.client.post("/api/extract-abstracts", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["id"],
                    body.get("id") if isinstance(body, dict) else None,
                )
        response = self.client.post(
            "/api/extract-abstracts",
            content='{"id":79665,',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(response.json()["id"])

    def test_download_failure_is_safe_and_cleans(self):
        def fail(url, path):
            path.write_bytes(b"parcial")
            raise DownloadError("secret@internal?token=secreto")

        self.download.download.side_effect = fail
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["id"], 79665)
        self.assertEqual(response.json()["phase"], "download")
        self.assertNotIn("secret", response.text)
        self.processor.assert_not_called()
        self.assertFalse(list(self.root.iterdir()))

    def test_processing_failure_is_safe_and_cleans(self):
        self.processor.side_effect = RuntimeError("prompt secreto")
        response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["id"], 79665)
        self.assertEqual(response.json()["phase"], "processing")
        self.assertNotIn("secreto", response.text)
        self.assertFalse(list(self.root.iterdir()))

    def test_non_pdf_content_never_reaches_pipeline(self):
        response = io.BytesIO(b"pagina HTML")
        response.status = 200
        response.headers = Message()
        downloader = PDFDownloader(opener=Mock(return_value=response))
        app = abstract_api.create_app(
            self.root, processor=self.processor, downloader=downloader
        )
        result = TestClient(app).post("/api/extract-abstracts", json=self.payload)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.json()["id"], 79665)
        self.assertEqual(result.json()["phase"], "download")
        self.processor.assert_not_called()
        self.assertFalse(list(self.root.iterdir()))

    def test_cleanup_failure_is_explicit(self):
        with patch.object(
            abstract_api.tempfile.TemporaryDirectory,
            "cleanup",
            side_effect=OSError("secreto"),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["id"], 79665)
        self.assertEqual(response.json()["phase"], "cleanup")
        self.assertNotIn("secreto", response.text)

    def test_concurrent_requests_same_id_are_isolated(self):
        barrier = threading.Barrier(2)
        paths = []

        def process(pdf, ws):
            paths.append(pdf)
            barrier.wait(timeout=10)
            self.assertTrue(pdf.exists())
            return self.process(pdf, ws)

        self.processor.side_effect = process
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: self.post(), range(2)))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertNotEqual(paths[0].parent, paths[1].parent)
        self.assertNotEqual(
            responses[0].json()["result"]["doc_id"],
            responses[1].json()["result"]["doc_id"],
        )
        self.assertFalse(list(self.root.iterdir()))
        self.assertEqual(len(list(self.logs.iterdir())), 2)

    def test_real_pipeline_json_and_no_mongodb(self):
        imported = builtins.__import__

        def guarded(name, *args, **kwargs):
            self.assertFalse(
                "mongo" in name
                or "external_provider" in name
                or "external_runner" in name
            )
            return imported(name, *args, **kwargs)

        snapshots = []

        def process(pdf, ws):
            result = abstract_api.process_pdf(
                pdf,
                ws,
                FakeTranscriber(
                    "Resumen\nEste documento estudia los sistemas de información sanitaria.\nPalabras clave: salud."
                ),
                FakeSummarizer(),
            )
            snapshots.append(json.loads(ws.abstract_path(pdf.stem).read_text()))
            return result

        self.processor.side_effect = process
        with (
            patch("builtins.__import__", side_effect=guarded),
            patch.dict("os.environ", {"PDFSUM_MONGODB_URI": "valor no utilizado"}),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], snapshots[0])
        self.assertFalse(list(self.root.iterdir()))

    def test_no_persistent_logs_recreates_no_files(self):
        app = abstract_api.create_app(
            self.root, processor=self.processor, downloader=self.download
        )
        response = TestClient(app).post("/api/extract-abstracts", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(list(self.root.iterdir()))

    def test_no_other_processing_endpoints(self):
        self.assertEqual(
            {route.path for route in self.app.routes if "POST" in route.methods},
            {"/api/extract-abstracts"},
        )


class TestPipelineReuse(unittest.TestCase):
    def test_optional_fastapi_dependency(self):
        imported = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "fastapi":
                raise ImportError("simulado")
            return imported(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=guarded),
            self.assertRaisesRegex(RuntimeError, r"pdfsum\[service\]"),
        ):
            abstract_api.create_app("sin-crear", processor=Mock())

    def test_refinement_fallback_error_is_sanitized(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inputs = root / "input"
            inputs.mkdir()
            pdf = inputs / "internal.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%%EOF")
            ws = Workspace(root)
            with (
                patch(
                    "pdfsum.adapters.abstract_batch.refine_abstracts",
                    side_effect=RuntimeError("token=secreto"),
                ),
                self.assertLogs(
                    "pdfsum.adapters.abstract_batch", level="WARNING"
                ) as captured,
            ):
                result = abstract_api.process_pdf(
                    pdf,
                    ws,
                    FakeTranscriber("Resumen\nTexto de resumen original."),
                    FakeSummarizer(),
                )
            self.assertEqual(result, json.loads(ws.abstract_path(pdf.stem).read_text()))
            self.assertNotIn("secreto", "".join(captured.output))
            self.assertNotIn(
                "secreto", (ws.report_path.parent / "events.jsonl").read_text()
            )

    @unittest.skipIf(TestClient is None, "Instala el extra opcional pdfsum[service]")
    def test_cli_wiring_and_configuration(self):
        with (
            tempfile.TemporaryDirectory() as td,
            patch.object(cli, "_build_transcriber") as transcriber,
            patch.object(cli, "_build_summarizer") as llm,
            patch(
                "pdfsum.adapters.abstract_api.process_pdf", return_value={}
            ) as process,
            patch("uvicorn.run") as serve,
        ):
            args = cli.build_parser().parse_args(
                [
                    "extract-abstracts-api",
                    "--workspace",
                    td,
                    "--host",
                    "0.0.0.0",
                    "--backend",
                    "ollama",
                    "--model",
                    "modelo",
                    "--vlm-model",
                    "vision",
                    "--lang",
                    "spa",
                ]
            )
            self.assertEqual(args.func(args), 0)
            app = serve.call_args.args[0]
            with patch("pdfsum.adapters.pdf_download.PDFDownloader.download"):
                response = TestClient(app).post(
                    "/api/extract-abstracts",
                    json={"id": 1, "url": "https://example.org/a.pdf"},
                )
            self.assertEqual(response.status_code, 200)
            transcriber.assert_called_once_with(False, "spa", vlm_model="vision")
            llm.assert_called_once_with(False, "ollama", "modelo")
            self.assertEqual(process.call_args.kwargs["backend"], "ollama")
            self.assertFalse(serve.call_args.kwargs["access_log"])
