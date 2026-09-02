"""Tests FASE9: default OCR multi-idioma (C1, C2)."""

import io
import unittest
from contextlib import redirect_stdout

from pdfsum.cli import build_parser, main


class TestDefaultLangMultilang(unittest.TestCase):
    def test_default_lang_run(self):
        """C1: default de --lang en run/transcribe/verify es por+eng+spa."""
        p = build_parser()
        for sub, argv in [
            ("run", ["run", "--in", "x", "--workspace", "y"]),
            ("transcribe", ["transcribe", "--in", "x", "--workspace", "y"]),
            ("verify", ["verify"]),
        ]:
            args = p.parse_args(argv)
            self.assertEqual(args.lang, "por+eng+spa", msg=f"subcomando {sub}")

    def test_lang_override_propagates(self):
        """C2: el usuario puede anadir idiomas via '+' y se propaga intacto."""
        p = build_parser()
        args = p.parse_args(
            [
                "run",
                "--in",
                "x",
                "--workspace",
                "y",
                "--lang",
                "por+eng+spa+fra",
            ]
        )
        self.assertEqual(args.lang, "por+eng+spa+fra")


class TestForceOcr(unittest.TestCase):
    def test_force_ocr_disponible_en_comandos_que_transcriben(self):
        """run, transcribe y verify aceptan --force-ocr."""
        parser = build_parser()
        commands = [
            ["run", "--in", "x", "--workspace", "y", "--force-ocr"],
            ["transcribe", "--in", "x", "--workspace", "y", "--force-ocr"],
            ["verify", "--force-ocr"],
        ]
        for argv in commands:
            with self.subTest(command=argv[0]):
                self.assertTrue(parser.parse_args(argv).force_ocr)

    def test_force_ocr_desactivado_por_defecto(self):
        """La conducta anterior se conserva cuando no se indica la bandera."""
        parser = build_parser()
        commands = [
            ["run", "--in", "x", "--workspace", "y"],
            ["transcribe", "--in", "x", "--workspace", "y"],
            ["verify"],
        ]
        for argv in commands:
            with self.subTest(command=argv[0]):
                self.assertFalse(parser.parse_args(argv).force_ocr)

    def test_force_ocr_aparece_en_la_ayuda(self):
        """La ayuda de cada comando que transcribe documenta --force-ocr."""
        for command in ("run", "transcribe", "verify"):
            with self.subTest(command=command), redirect_stdout(io.StringIO()) as out:
                with self.assertRaises(SystemExit) as raised:
                    main([command, "--help"])
                self.assertEqual(raised.exception.code, 0)
                self.assertIn("--force-ocr", out.getvalue())


if __name__ == "__main__":
    unittest.main()
