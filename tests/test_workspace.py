"""Test del almacén canónico (criterio C1)."""

import unittest
from pathlib import Path

from pdfsum.workspace import Workspace


class TestWorkspace(unittest.TestCase):
    def test_layout(self):
        """C1: rutas canónicas ocr/, summaries/, y helpers por doc_id."""
        ws = Workspace("/tmp/wsX")
        self.assertEqual(ws.ocr_dir, Path("/tmp/wsX/ocr"))
        self.assertEqual(ws.summaries_dir, Path("/tmp/wsX/summaries"))
        self.assertEqual(ws.ocr_path("d1"), Path("/tmp/wsX/ocr/d1.txt"))
        self.assertEqual(ws.summary_path("d1"), Path("/tmp/wsX/summaries/d1.json"))
        self.assertEqual(ws.report_path, Path("/tmp/wsX/summaries/report.json"))
        self.assertEqual(ws.lilacs_path, Path("/tmp/wsX/lilacs.json"))


if __name__ == "__main__":
    unittest.main()
