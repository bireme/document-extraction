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
from pdfsum.adapters import pdfsum_api
from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.pdf_download import DownloadError, PDFDownloader
from pdfsum.workspace import Workspace


@unittest.skipIf(TestClient is None, "Instala el extra opcional pdfsum[service]")
class TestPDFSumAPI(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "workspace"
        self.logs = self.base / "logs"
        self.inputs = self.base / "entrada"
        self.download = Mock()
        self.download.download.side_effect = lambda url, path: path.write_bytes(
            b"%PDF-1.4\n%%EOF\n"
        )
        self.processor = Mock(side_effect=self.process)
        self.app = pdfsum_api.create_app(
            self.root,
            processor=self.processor,
            logs_dir=self.logs,
            downloader=self.download,
            input_root=self.inputs,
        )
        self.client = TestClient(self.app)
        self.payload = {
            "id": 79665,
            "command": "extract-abstracts",
            "url": "https://public.example/doc.pdf?token=secreto",
        }

    def process(self, pdf, ws, command):
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
        return self.client.post("/api/pdfsum", json={**self.payload, **changes})

    def local_pdf(self):
        original = self.inputs / "MS-all" / "79665_articulo.pdf"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return original

    def post_folder(self, **changes):
        return self.client.post(
            "/api/pdfsum",
            json={
                "id": 79665,
                "command": "extract-abstracts",
                "folder": "MS-all",
                **changes,
            },
        )

    def test_folder_isolation_original_and_commands(self):
        original = self.local_pdf()
        content = original.read_bytes()
        other = original.with_name("56186_otro.pdf")
        other.write_bytes(content)
        sentinel = self.root / "conservar.txt"
        sentinel.write_text("conservar")

        def process(pdf, ws, command):
            self.assertNotEqual(pdf, original)
            self.assertEqual(pdf.parent.name, "input")
            self.assertEqual(pdf.parent.parent, ws.root)
            self.assertEqual(list(pdf.parent.iterdir()), [pdf])
            self.assertEqual(pdf.read_bytes(), content)
            pdf.write_bytes(content + b"\n")
            return pdfsum_api.process_pdf(
                pdf,
                ws,
                FakeTranscriber("Resumen\nTexto original."),
                FakeSummarizer(),
                command=command,
            )

        self.processor.side_effect = process
        for command in ["extract-abstracts", "transcribe", "run"]:
            with self.subTest(command=command):
                response = self.post_folder(command=command)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(original.read_bytes(), content)
                self.assertEqual(other.read_bytes(), content)
                self.assertEqual(list(self.root.iterdir()), [sentinel])
        self.download.download.assert_not_called()

    def test_folder_missing_and_ambiguous(self):
        response = self.post_folder()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["phase"], "seleccion")
        original = self.local_pdf()
        response = self.post_folder(id=75798)
        self.assertEqual(response.status_code, 404)
        original.with_name("79665_corregido.pdf").write_bytes(original.read_bytes())
        response = self.post_folder()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_type"], "SelectionError")
        self.assertFalse(list(self.root.iterdir()))
        self.processor.assert_not_called()
        self.download.download.assert_not_called()

    def test_folder_validation_and_exclusive_sources(self):
        for folder in [
            "../MS-all",
            "/input/MS-all",
            "MS-all/subdir",
            ".",
            "..",
            "MS-all\\subdir",
            "",
            None,
            [],
            4,
            "lote\n",
        ]:
            with self.subTest(folder=folder):
                response = self.post_folder(folder=folder)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["phase"], "validacion")
        for changes in [{"url": self.payload["url"]}, {"extra": True}]:
            self.assertEqual(self.post_folder(**changes).status_code, 422)
        response = self.client.post("/api/pdfsum", json={"id": 79665, "command": "run"})
        self.assertEqual(response.status_code, 422)
        self.processor.assert_not_called()
        self.download.download.assert_not_called()

    def test_selection_literal_names_and_regular_files(self):
        original = self.local_pdf()
        for name in [
            "179665_articulo.pdf",
            "79665.pdf",
            "79665_articulo.pdf.bak",
            "79665_articulo.PDF",
        ]:
            original.with_name(name).write_bytes(b"otro")
        original.with_name("79665_directorio.pdf").mkdir()
        self.assertEqual(pdfsum_api.select_pdf(self.inputs, "MS-all", 79665), original)
        for identity in ["*", "../79665", "[0-9]*"]:
            with self.subTest(identity=identity):
                self.assertEqual(self.post_folder(id=identity).status_code, 404)
        for folder in ["MS-1-10", "lote_2026", "lote.2026"]:
            original.parent.rename(self.inputs / folder)
            self.assertEqual(self.post_folder(folder=folder).status_code, 200)
            (self.inputs / folder).rename(original.parent)

    def test_folder_symlinks_are_rejected(self):
        original = self.local_pdf()
        (self.inputs / "enlace").symlink_to(original.parent, target_is_directory=True)
        self.assertEqual(self.post_folder(folder="enlace").status_code, 409)
        original.with_name("75798_enlace.pdf").symlink_to(original)
        self.assertEqual(self.post_folder(id=75798).status_code, 409)
        self.processor.assert_not_called()

    def test_folder_read_and_copy_errors_are_safe(self):
        self.local_pdf()
        for target in ["select_pdf", "shutil.copyfile"]:
            with (
                self.subTest(target=target),
                patch(
                    "pdfsum.adapters.pdfsum_api." + target,
                    side_effect=PermissionError("/ruta/privada token=secreto"),
                ),
                self.assertLogs("pdfsum.adapters.pdfsum_api", level="INFO") as captured,
            ):
                response = self.post_folder()
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json()["phase"], "seleccion")
                self.assertNotIn("secreto", response.text + "".join(captured.output))
                self.assertNotIn("/ruta/privada", response.text)
                self.assertFalse(list(self.root.iterdir()))
        self.processor.assert_not_called()
        logs = "".join(p.read_text() for p in self.logs.rglob("*.jsonl"))
        self.assertNotIn("secreto", logs)

    def test_concurrent_folder_and_url_requests_are_isolated(self):
        original = self.local_pdf()
        content = original.read_bytes()
        barrier = threading.Barrier(3)
        paths = []

        def process(pdf, ws, command):
            paths.append(pdf)
            barrier.wait(timeout=10)
            self.assertEqual(list(pdf.parent.iterdir()), [pdf])
            return self.process(pdf, ws, command)

        self.processor.side_effect = process
        with ThreadPoolExecutor(max_workers=3) as executor:
            responses = list(
                executor.map(
                    lambda local: self.post_folder() if local else self.post(),
                    [True, True, False],
                )
            )
        self.assertEqual([r.status_code for r in responses], [200, 200, 200])
        self.assertEqual(len({p.parent for p in paths}), 3)
        self.assertFalse(list(self.root.iterdir()))
        self.assertEqual(original.read_bytes(), content)
        self.download.download.assert_called_once()

    def test_success_preserves_result_identity_and_cleans(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.download.download.assert_called_once()
        self.assertEqual(data["id"], 79665)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["result"]["abstracts"][0]["text"], "Texto original")
        self.assertFalse(list(self.root.iterdir()))
        logs = "".join(p.read_text() for p in self.logs.rglob("*.jsonl"))
        self.assertNotIn("secreto", logs)
        self.assertNotIn("contenido sensible", logs)
        self.assertIn("request_completed", logs)
        events = [json.loads(line) for line in logs.splitlines()]
        self.assertEqual(
            [event["phase"] for event in events if event["event"] == "phase_started"],
            ["descarga", "procesamiento"],
        )

    def test_commands_and_natural_results(self):
        for command, result in [
            ("extract-abstracts", {"abstracts": []}),
            ("transcribe", "Texto transcrito\ncon acentos: información."),
            ("run", {"doc_id": "interno", "_qa": {"passed": True}}),
        ]:
            with self.subTest(command=command):
                self.processor.side_effect = None
                self.processor.return_value = result
                response = self.post(command=command)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {
                        "id": 79665,
                        "command": command,
                        "status": "completed",
                        "result": result,
                    },
                )
                self.assertEqual(self.processor.call_args.args[2], command)

    def test_rejects_unsupported_and_missing_command(self):
        for command in ["summarize", "desconocido", "run; echo secreto", None, [], {}]:
            with self.subTest(command=command):
                response = self.post(command=command)
                self.assertEqual(response.status_code, 422)
                self.assertIsNone(response.json()["command"])
                self.assertNotIn("secreto", response.text)
        payload = {k: v for k, v in self.payload.items() if k != "command"}
        self.assertEqual(self.client.post("/api/pdfsum", json=payload).status_code, 422)
        self.download.download.assert_not_called()
        self.processor.assert_not_called()
        self.assertEqual(
            self.client.post("/api/extract-abstracts", json=self.payload).status_code,
            404,
        )

    def test_real_pipelines_and_cleanup_preserve_other_execution(self):
        other = self.root / "otra-ejecucion"
        other.mkdir()
        sentinel = other / "resultado.json"
        sentinel.write_text("conservar")
        snapshots = {}

        def process(pdf, ws, command):
            result = pdfsum_api.process_pdf(
                pdf,
                ws,
                FakeTranscriber("Resumen\nTexto original del documento."),
                FakeSummarizer(),
                command=command,
            )
            path = {
                "extract-abstracts": ws.abstract_path(pdf.stem),
                "transcribe": ws.ocr_path(pdf.stem),
                "run": ws.summary_path(pdf.stem),
            }[command]
            snapshots[command] = path.read_text(encoding="utf-8")
            return result

        self.processor.side_effect = process
        for command in ["extract-abstracts", "transcribe", "run"]:
            with self.subTest(command=command):
                response = self.post(command=command)
                self.assertEqual(response.status_code, 200, response.text)
                expected = snapshots[command]
                if command != "transcribe":
                    expected = json.loads(expected)
                self.assertEqual(response.json()["result"], expected)
                self.assertEqual(list(self.root.iterdir()), [other])
                self.assertEqual(sentinel.read_text(), "conservar")

    def test_real_processing_failures_are_safe_for_each_command(self):
        transcriber = Mock()
        transcriber.transcribe.side_effect = RuntimeError(
            "Traceback https://user:password@example.org/a?token=secreto prompt contenido del PDF"
        )
        self.processor.side_effect = lambda pdf, ws, command: pdfsum_api.process_pdf(
            pdf,
            ws,
            transcriber,
            FakeSummarizer(),
            command=command,
        )
        for command in ["extract-abstracts", "transcribe", "run"]:
            with self.subTest(command=command):
                response = self.post(command=command)
                self.assertEqual(response.status_code, 500, response.text)
                self.assertEqual(response.json()["command"], command)
                self.assertEqual(response.json()["phase"], "procesamiento")
                self.assertEqual(response.json()["error"], "No se pudo procesar el PDF")
                for sensitive in [
                    "Traceback",
                    "https://",
                    "password",
                    "secreto",
                    "prompt",
                    "contenido del PDF",
                ]:
                    self.assertNotIn(sensitive, response.text)
                self.assertFalse(list(self.root.iterdir()))
        logs = "".join(p.read_text() for p in self.logs.rglob("*.json*"))
        self.assertNotIn("secreto", logs)

    def test_run_report_failure_rejects_existing_output(self):
        def fail_with_output(in_dir, ws, *args, **kwargs):
            pdf = next(Path(in_dir).glob("*.pdf"))
            output = ws.summary_path(pdf.stem)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text('{"detalle": "contenido sensible"}')
            return {"progress": {"failed": 1}}

        self.processor.side_effect = lambda pdf, ws, command: pdfsum_api.process_pdf(
            pdf, ws, Mock(), Mock(), command=command
        )
        with patch.object(pdfsum_api, "run_batch_pdfs", side_effect=fail_with_output):
            response = self.post(command="run")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {
                "id": 79665,
                "command": "run",
                "status": "failed",
                "phase": "procesamiento",
                "error_type": "ProcessingError",
                "error": "No se pudo procesar el PDF",
            },
        )
        self.assertFalse(list(self.root.iterdir()))

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
                self.assertEqual(response.json()["phase"], "validacion")
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
                response = self.client.post("/api/pdfsum", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["id"],
                    body.get("id") if isinstance(body, dict) else None,
                )
        response = self.client.post(
            "/api/pdfsum",
            content='{"id":79665,',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(response.json()["id"])
        self.assertEqual(response.json()["phase"], "validacion")

    def test_download_failure_is_safe_and_cleans(self):
        def fail(url, path):
            path.write_bytes(b"parcial")
            raise DownloadError("secret@internal?token=secreto")

        self.download.download.side_effect = fail
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["id"], 79665)
        self.assertEqual(response.json()["phase"], "descarga")
        self.assertNotIn("secret", response.text)
        self.processor.assert_not_called()
        self.assertFalse(list(self.root.iterdir()))

    def test_processing_failure_is_safe_and_cleans(self):
        self.processor.side_effect = RuntimeError("prompt secreto")
        response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["id"], 79665)
        self.assertEqual(response.json()["phase"], "procesamiento")
        self.assertNotIn("secreto", response.text)
        self.assertFalse(list(self.root.iterdir()))

    def test_non_pdf_content_never_reaches_pipeline(self):
        response = io.BytesIO(b"pagina HTML")
        response.status = 200
        response.headers = Message()
        downloader = PDFDownloader(opener=Mock(return_value=response))
        app = pdfsum_api.create_app(
            self.root, processor=self.processor, downloader=downloader
        )
        result = TestClient(app).post("/api/pdfsum", json=self.payload)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.json()["id"], 79665)
        self.assertEqual(result.json()["phase"], "descarga")
        self.processor.assert_not_called()
        self.assertFalse(list(self.root.iterdir()))

    def test_cleanup_failure_is_explicit(self):
        with patch.object(
            pdfsum_api.tempfile.TemporaryDirectory,
            "cleanup",
            side_effect=OSError("secreto"),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["id"], 79665)
        self.assertEqual(response.json()["phase"], "limpieza")
        self.assertNotIn("secreto", response.text)

    def test_concurrent_requests_same_id_are_isolated(self):
        barrier = threading.Barrier(3)
        paths = []

        def process(pdf, ws, command):
            paths.append(pdf)
            barrier.wait(timeout=10)
            self.assertTrue(pdf.exists())
            return self.process(pdf, ws, command)

        self.processor.side_effect = process
        with ThreadPoolExecutor(max_workers=3) as executor:
            responses = list(
                executor.map(
                    lambda command: self.post(command=command),
                    ["extract-abstracts", "transcribe", "run"],
                )
            )
        self.assertEqual([r.status_code for r in responses], [200, 200, 200])
        self.assertEqual(len({p.parent for p in paths}), 3)
        self.assertNotEqual(
            responses[0].json()["result"]["doc_id"],
            responses[1].json()["result"]["doc_id"],
        )
        self.assertFalse(list(self.root.iterdir()))
        self.assertEqual(len(list(self.logs.iterdir())), 3)

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

        def process(pdf, ws, command):
            result = pdfsum_api.process_pdf(
                pdf,
                ws,
                FakeTranscriber(
                    "Resumen\nEste documento estudia los sistemas de información sanitaria.\nPalabras clave: salud."
                ),
                FakeSummarizer(),
                command="extract-abstracts",
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
        app = pdfsum_api.create_app(
            self.root, processor=self.processor, downloader=self.download
        )
        response = TestClient(app).post("/api/pdfsum", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(list(self.root.iterdir()))

    def test_no_other_processing_endpoints(self):
        self.assertEqual(
            {route.path for route in self.app.routes if "POST" in route.methods},
            {"/api/pdfsum"},
        )


class TestPipelineReuse(unittest.TestCase):
    def test_dispatch_calls_only_selected_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "input" / "interno.pdf"
            pdf.parent.mkdir()
            pdf.write_bytes(b"%PDF-1.4\n%%EOF")
            ws = Workspace(td)
            for path, content in [
                (ws.abstract_path(pdf.stem), "{}"),
                (ws.summary_path(pdf.stem), "{}"),
                (ws.ocr_path(pdf.stem), "Texto"),
            ]:
                path.parent.mkdir(exist_ok=True)
                path.write_text(content)
            for command, selected in [
                ("extract-abstracts", 0),
                ("transcribe", 1),
                ("run", 2),
            ]:
                with (
                    self.subTest(command=command),
                    patch.object(
                        pdfsum_api, "extract_abstracts_from_pdfs"
                    ) as abstracts,
                    patch.object(pdfsum_api, "transcribe_pdfs") as transcribe,
                    patch.object(
                        pdfsum_api,
                        "run_batch_pdfs",
                        return_value={"progress": {"failed": 0}},
                    ) as run,
                    patch(
                        "subprocess.Popen",
                        side_effect=AssertionError("No ejecutar shell"),
                    ),
                ):
                    pdfsum_api.process_pdf(pdf, ws, Mock(), Mock(), command=command)
                    for index, pipeline in enumerate([abstracts, transcribe, run]):
                        self.assertEqual(pipeline.call_count, int(index == selected))
                    if command == "transcribe":
                        self.assertEqual(transcribe.call_args.kwargs, {})
                    if command == "run":
                        self.assertEqual(
                            set(run.call_args.kwargs), {"long_strategy", "format_error"}
                        )

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
            pdfsum_api.create_app("sin-crear", processor=Mock())

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
                    "pdfsum.abstract_extraction.refine_abstracts",
                    side_effect=RuntimeError("token=secreto"),
                ),
                self.assertLogs(
                    "pdfsum.adapters.abstract_batch", level="WARNING"
                ) as captured,
            ):
                result = pdfsum_api.process_pdf(
                    pdf,
                    ws,
                    FakeTranscriber("Resumen\nTexto de resumen original."),
                    FakeSummarizer(),
                    command="extract-abstracts",
                )
            self.assertEqual(result, json.loads(ws.abstract_path(pdf.stem).read_text()))
            self.assertNotIn("secreto", "".join(captured.output))
            self.assertNotIn(
                "secreto", (ws.report_path.parent / "events.jsonl").read_text()
            )

    @unittest.skipIf(TestClient is None, "Instala el extra opcional pdfsum[service]")
    def test_cli_transcribe_does_not_build_summarizer_and_preserves_api(self):
        self.assertIs(
            cli.build_parser().parse_args(["api", "--workspace", "workspace"]).func,
            cli.cmd_api,
        )
        with (
            tempfile.TemporaryDirectory() as td,
            patch.object(cli, "_build_transcriber"),
            patch.object(cli, "_build_summarizer") as llm,
            patch(
                "pdfsum.adapters.pdfsum_api.process_pdf", return_value="Texto"
            ) as process,
            patch("uvicorn.run") as serve,
        ):
            args = cli.build_parser().parse_args(
                ["processing-api", "--workspace", td, "--long-strategy", "blocks"]
            )
            self.assertEqual(args.func(args), 0)
            with patch("pdfsum.adapters.pdf_download.PDFDownloader.download"):
                response = TestClient(serve.call_args.args[0]).post(
                    "/api/pdfsum",
                    json={
                        "id": 1,
                        "command": "transcribe",
                        "url": "https://example.org/a.pdf",
                    },
                )
            self.assertEqual(response.status_code, 200)
            llm.assert_not_called()
            self.assertEqual(process.call_args.kwargs["command"], "transcribe")
            self.assertEqual(process.call_args.kwargs["long_strategy"], "blocks")

    @unittest.skipIf(TestClient is None, "Instala el extra opcional pdfsum[service]")
    def test_cli_wiring_and_configuration(self):
        with (
            tempfile.TemporaryDirectory() as td,
            patch.object(cli, "_build_transcriber") as transcriber,
            patch.object(cli, "_build_summarizer") as llm,
            patch("pdfsum.adapters.pdfsum_api.process_pdf", return_value={}) as process,
            patch("uvicorn.run") as serve,
        ):
            args = cli.build_parser().parse_args(
                [
                    "processing-api",
                    "--workspace",
                    td,
                    "--input-root",
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
            local = Path(td) / "MS-all" / "1_articulo.pdf"
            local.parent.mkdir()
            local.write_bytes(b"%PDF-1.4\n%%EOF")
            with patch(
                "pdfsum.adapters.pdf_download.PDFDownloader.download"
            ) as download:
                response = TestClient(app).post(
                    "/api/pdfsum",
                    json={"id": 1, "command": "transcribe", "folder": "MS-all"},
                )
                self.assertEqual(response.status_code, 200)
                download.assert_not_called()
            transcriber.reset_mock()
            with patch("pdfsum.adapters.pdf_download.PDFDownloader.download"):
                response = TestClient(app).post(
                    "/api/pdfsum",
                    json={
                        "id": 1,
                        "command": "extract-abstracts",
                        "url": "https://example.org/a.pdf",
                    },
                )
            self.assertEqual(response.status_code, 200)
            transcriber.assert_called_once_with(False, "spa", vlm_model="vision")
            llm.assert_called_once_with(False, "ollama", "modelo")
            self.assertEqual(process.call_args.kwargs["backend"], "ollama")
            self.assertFalse(serve.call_args.kwargs["access_log"])
