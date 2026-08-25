"""Tests del verificador de aceptación (criterios C5, C6)."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pdfsum.acceptance import acceptance_verdict, load_control_set


class TestAcceptance(unittest.TestCase):
    def test_load_set(self):
        """C5: carga un set de control JSON."""
        with TemporaryDirectory() as td:
            p = Path(td) / "cs.json"
            p.write_text(
                json.dumps(
                    [
                        {
                            "doc_id": "d1",
                            "expected_lang": "pt",
                            "expected_type": "articulo",
                            "expected_terms": ["a", "b"],
                        },
                    ]
                ),
                encoding="utf-8",
            )
            cases = load_control_set(str(p))
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0].doc_id, "d1")
            self.assertEqual(cases[0].expected_terms, ["a", "b"])

    def test_verdict(self):
        """C6: PASS si cobertura>=umbral y aciertan idioma y tipo."""
        good = {
            "total": 2,
            "coverage_media": 0.9,
            "lang_aciertos": 2,
            "type_aciertos": 2,
        }
        self.assertTrue(acceptance_verdict(good, 0.6).passed)

        low_cov = {
            "total": 2,
            "coverage_media": 0.4,
            "lang_aciertos": 2,
            "type_aciertos": 2,
        }
        self.assertFalse(acceptance_verdict(low_cov, 0.6).passed)

        lang_fail = {
            "total": 2,
            "coverage_media": 0.9,
            "lang_aciertos": 1,
            "type_aciertos": 2,
        }
        v = acceptance_verdict(lang_fail, 0.6)
        self.assertFalse(v.passed)
        self.assertFalse(v.lang_ok)


if __name__ == "__main__":
    unittest.main()
