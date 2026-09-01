"""Test del almacén canónico (criterio C1)."""

import unittest
from pathlib import Path

from pdfsum.workspace import Workspace


class TestWorkspace(unittest.TestCase):
    def test_c01_layout(self):
        """C01: rutas canónicas ocr/, summaries/, y helpers por doc_id."""
        ws = Workspace("/tmp/wsX")
        self.assertEqual(ws.ocr_dir, Path("/tmp/wsX/ocr"))
        self.assertEqual(ws.summaries_dir, Path("/tmp/wsX/summaries"))
        self.assertEqual(ws.ocr_path("d1"), Path("/tmp/wsX/ocr/d1.txt"))
        self.assertEqual(ws.summary_path("d1"), Path("/tmp/wsX/summaries/d1.json"))
        self.assertEqual(ws.report_path, Path("/tmp/wsX/summaries/report.json"))
        self.assertEqual(ws.lilacs_path, Path("/tmp/wsX/lilacs.json"))

    def test_ids_maliciosos_no_escapan_del_workspace(self):
        """Los IDs no pueden construir rutas fuera de los directorios canónicos."""
        ws = Workspace("/tmp/wsX")
        ids_invalidos = (
            "",
            "../escape",
            "../../archivo",
            "/tmp/absoluto",
            "%2e%2e",
            r"..\escape",
            "control\x00",
        )

        for doc_id in ids_invalidos:
            with self.subTest(doc_id=repr(doc_id)):
                with self.assertRaises(ValueError):
                    ws.ocr_path(doc_id)
                with self.assertRaises(ValueError):
                    ws.summary_path(doc_id)
                with self.assertRaises(ValueError):
                    ws.bibframe_path(doc_id)


if __name__ == "__main__":
    unittest.main()
