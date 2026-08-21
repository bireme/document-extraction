"""Tests FASE9: default OCR multi-idioma (C1, C2)."""
import unittest

from pdfsum.cli import build_parser


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
        args = p.parse_args([
            "run", "--in", "x", "--workspace", "y",
            "--lang", "por+eng+spa+fra",
        ])
        self.assertEqual(args.lang, "por+eng+spa+fra")


if __name__ == "__main__":
    unittest.main()
