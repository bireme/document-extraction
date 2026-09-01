"""Pruebas unitarias de contrato para adapters de procesos y servicios externos."""

import json
import subprocess
import unittest
from unittest.mock import patch

from PIL import Image

from pdfsum.adapters.ocr_transcriber import OcrTranscriber, _pdfinfo_pages, _run
from pdfsum.adapters.ollama_summarizer import OllamaSummarizer
from pdfsum.adapters.vlm_ocr import VlmPageOCR
from pdfsum.contract import SourceKind, SummarizeRequest


class _Response:
    def __init__(self, payload: object):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class TestOcrTranscriber(unittest.TestCase):
    def test_run_envia_comando_timeout_y_devuelve_stdout(self):
        """El wrapper conserva argumentos, timeout y salida del proceso."""
        completed = subprocess.CompletedProcess([], 0, stdout="salida", stderr="")
        with patch("subprocess.run", return_value=completed) as run:
            output = _run(["pdfinfo", "documento.pdf"], timeout=17)

        self.assertEqual(output, "salida")
        run.assert_called_once_with(
            ["pdfinfo", "documento.pdf"],
            capture_output=True,
            text=True,
            timeout=17,
            check=False,
        )

    def test_run_propaga_timeout(self):
        """Un timeout externo no se convierte silenciosamente en éxito."""
        with (
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(["pdfinfo"], 3),
            ),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            _run(["pdfinfo", "documento.pdf"], timeout=3)

    def test_pdfinfo_parsea_paginas_y_payload_invalido(self):
        with patch(
            "pdfsum.adapters.ocr_transcriber._run",
            return_value="Title: Uno\nPages: 7\n",
        ):
            self.assertEqual(_pdfinfo_pages("documento.pdf"), 7)
        with (
            patch(
                "pdfsum.adapters.ocr_transcriber._run",
                return_value="Pages: inválido\n",
            ),
            self.assertRaises(ValueError),
        ):
            _pdfinfo_pages("documento.pdf")

    def test_configuracion_invalida_informa_herramienta_faltante(self):
        with (
            patch(
                "pdfsum.adapters.ocr_transcriber.shutil.which",
                side_effect=lambda tool: (
                    None if tool == "pdfinfo" else f"/usr/bin/{tool}"
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "pdfinfo"),
        ):
            OcrTranscriber()

    def test_pdf_nativo_evita_tesseract(self):
        with (
            patch(
                "pdfsum.adapters.ocr_transcriber.shutil.which", return_value="/bin/x"
            ),
            patch("pdfsum.adapters.ocr_transcriber._pdfinfo_pages", return_value=2),
            patch(
                "pdfsum.adapters.ocr_transcriber._run",
                return_value="texto nativo " * 30,
            ) as run,
        ):
            result = OcrTranscriber().transcribe("documento.pdf")

        self.assertEqual(result.source_kind, SourceKind.NATIVO)
        self.assertEqual(result.pages, 2)
        self.assertEqual(run.call_count, 1)

    def test_escaneado_sin_tesseract_degrada_al_texto_nativo(self):
        available = {"pdftotext", "pdfinfo"}
        with (
            patch(
                "pdfsum.adapters.ocr_transcriber.shutil.which",
                side_effect=lambda tool: f"/bin/{tool}" if tool in available else None,
            ),
            patch("pdfsum.adapters.ocr_transcriber._pdfinfo_pages", return_value=1),
            patch("pdfsum.adapters.ocr_transcriber._run", return_value=""),
        ):
            result = OcrTranscriber().transcribe("escaneado.pdf")

        self.assertEqual(result.source_kind, SourceKind.ESCANEADO)
        self.assertEqual(result.text, "")

    def test_ocr_renderiza_y_transcribe_cada_pagina(self):
        commands: list[list[str]] = []

        def fake_run(command, timeout=120):
            commands.append(command)
            if command[0] == "pdftotext":
                return ""
            if command[0] == "pdftoppm":
                Image.new("L", (40, 30), 255).save(f"{command[-1]}-1.jpg")
                return ""
            return "texto reconocido"

        with (
            patch(
                "pdfsum.adapters.ocr_transcriber.shutil.which", return_value="/bin/x"
            ),
            patch("pdfsum.adapters.ocr_transcriber._pdfinfo_pages", return_value=1),
            patch("pdfsum.adapters.ocr_transcriber._run", side_effect=fake_run),
        ):
            result = OcrTranscriber(lang="spa", dpi=144).transcribe("imagen.pdf")

        self.assertIn("texto reconocido", result.text)
        render = next(command for command in commands if command[0] == "pdftoppm")
        ocr = next(command for command in commands if command[0] == "tesseract")
        self.assertIn("144", render)
        self.assertEqual(ocr[ocr.index("-l") + 1], "spa")


class TestVlmPageOCR(unittest.TestCase):
    def test_comando_limpia_ansi_y_bloque_de_razonamiento(self):
        completed = subprocess.CompletedProcess(
            [], 0, stdout="\x1b[31m<think>interno</think> Texto final \x1b[0m"
        )
        with patch("subprocess.run", return_value=completed) as run:
            output = VlmPageOCR(model="vision:test", timeout=19).ocr_image(
                "página uno.png", "spa"
            )

        self.assertEqual(output, "Texto final")
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["ollama", "run", "vision:test"])
        self.assertIn("página uno.png", command[3])
        self.assertEqual(run.call_args.kwargs["timeout"], 19)

    def test_idioma_desconocido_usa_prompt_portugues(self):
        completed = subprocess.CompletedProcess([], 0, stdout="texto")
        with patch("subprocess.run", return_value=completed) as run:
            VlmPageOCR().ocr_image("imagen.png", "desconocido")
        self.assertIn("português", run.call_args.args[0][3])

    def test_timeout_y_error_externo_devuelven_vacio(self):
        for error in (subprocess.TimeoutExpired(["ollama"], 1), OSError("sin binario")):
            with (
                self.subTest(error=type(error).__name__),
                patch("subprocess.run", side_effect=error),
            ):
                self.assertEqual(VlmPageOCR().ocr_image("imagen.png", "spa"), "")

    def test_respuesta_vacia_se_conserva_vacia(self):
        completed = subprocess.CompletedProcess([], 1, stdout="")
        with patch("subprocess.run", return_value=completed):
            self.assertEqual(VlmPageOCR().ocr_image("imagen.png", "spa"), "")


class TestOllamaSummarizer(unittest.TestCase):
    def test_payload_endpoint_timeout_y_parsing(self):
        captured = {}

        def urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response({"response": "## Título\nResultado estable\n"})

        with patch("urllib.request.urlopen", side_effect=urlopen):
            summarizer = OllamaSummarizer(
                model="qwen:test", num_ctx=8192, endpoint="http://ollama/api/generate"
            )
            result = summarizer.summarize(
                SummarizeRequest("doc", "texto fuente", "es", "C")
            )

        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(captured["request"].full_url, "http://ollama/api/generate")
        self.assertEqual(payload["model"], "qwen:test")
        self.assertEqual(payload["options"]["num_ctx"], 8192)
        self.assertFalse(payload["stream"])
        self.assertEqual(captured["timeout"], 600)
        self.assertEqual(result["titulo"], "Resultado estable")

    def test_payload_invalido_y_timeout_no_pasan_como_respuesta_valida(self):
        invalid = _Response({"campo": "sin respuesta"})
        with patch("urllib.request.urlopen", return_value=invalid):
            self.assertEqual(OllamaSummarizer()._call("prompt"), "")
        with (
            patch("urllib.request.urlopen", side_effect=TimeoutError("demora")),
            self.assertRaises(TimeoutError),
        ):
            OllamaSummarizer()._call("prompt")


if __name__ == "__main__":
    unittest.main()
