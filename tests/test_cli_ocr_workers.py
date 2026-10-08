"""Límites OCR compartidos por CLI, configuración y adaptador."""

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from pdfsum.cli import _build_transcriber, build_parser, main


class TestOcrWorkersCLI(unittest.TestCase):
    def test_opciones_en_todos_los_comandos_pdf(self):
        for command in (
            "run",
            "transcribe",
            "extract-abstracts",
            "worker",
            "verify",
            "processing-api",
        ):
            argv = [command, "--workspace", "destino"]
            if command in ("run", "transcribe", "extract-abstracts"):
                argv += ["--in", "entrada"]
            with self.subTest(command=command):
                args = build_parser().parse_args(
                    argv + ["--ocr-workers", "4", "--vlm-workers", "2"]
                )
                self.assertEqual((args.ocr_workers, args.vlm_workers), (4, 2))

    def test_factory_config_y_precedencia_cli(self):
        for explicit, expected in (
            ({}, (4, 2)),
            ({"ocr_workers": 1, "vlm_workers": 1}, (1, 1)),
        ):
            with (
                self.subTest(explicit=explicit),
                patch(
                    "pdfsum.cli.get_config_value",
                    side_effect=lambda key, default: {
                        "ocr_workers": 4,
                        "vlm_workers": 2,
                    }.get(key, default),
                ),
                patch("pdfsum.adapters.doctor._ollama_models", return_value=["modelo"]),
                patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/bin/x"),
            ):
                tx = _build_transcriber(False, "spa", vlm_model="modelo", **explicit)
                self.assertEqual((tx.ocr_workers, tx.vlm_workers), expected)
                self.assertEqual(tx.vlm.model, "modelo")

    def test_factory_defaults(self):
        with (
            patch(
                "pdfsum.cli.get_config_value", side_effect=lambda key, default: default
            ),
            patch("pdfsum.adapters.doctor._ollama_models", return_value=["modelo"]),
            patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/bin/x"),
        ):
            tx = _build_transcriber(False, "spa", vlm_model="modelo")
        self.assertEqual((tx.ocr_workers, tx.vlm_workers), (2, 1))

    def test_rechaza_cli_y_config_invalidas_incluso_fake(self):
        for name in ("ocr_workers", "vlm_workers"):
            for value in (0, -2):
                with (
                    self.subTest(name=name, value=value),
                    redirect_stderr(io.StringIO()),
                ):
                    rc = main(
                        [
                            "transcribe",
                            "--in",
                            "entrada",
                            "--workspace",
                            "destino",
                            "--fake",
                            f"--{name.replace('_', '-')}",
                            str(value),
                        ]
                    )
                    self.assertEqual(rc, 2)
            for value in (0, -1, True, 2.5, "2"):
                with (
                    self.subTest(name=name, config=value),
                    patch(
                        "pdfsum.cli.get_config_value",
                        side_effect=lambda key, default, value=value, name=name: (
                            value if key == name else default
                        ),
                    ),
                    self.assertRaisesRegex(ValueError, name),
                ):
                    _build_transcriber(True, "spa")

    def test_transcribe_propaga_limites(self):
        with (
            patch("pdfsum.cli._build_transcriber") as factory,
            patch("pdfsum.adapters.pdf_batch.transcribe_pdfs", return_value={}),
        ):
            rc = main(
                [
                    "transcribe",
                    "--in",
                    "entrada",
                    "--workspace",
                    "destino",
                    "--ocr-workers",
                    "4",
                    "--vlm-workers",
                    "2",
                ]
            )
        self.assertEqual(rc, 0)
        factory.assert_called_once_with(
            False, "por+eng+spa", vlm_model=None, ocr_workers=4, vlm_workers=2
        )
