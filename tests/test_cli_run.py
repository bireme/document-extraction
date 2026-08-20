"""Tests de los subcomandos run y transcribe (criterios C6, C7)."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pdfsum.cli import main


def _make_pdfs(d: Path, n):
    for i in range(n):
        (d / f"doc{i}.pdf").write_bytes(b"%PDF-1.4 fake")


class TestCLIRun(unittest.TestCase):
    def test_cli_run(self):
        """C6: 'run --fake' ejecuta flujo completo desde PDFs."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "pdfs"; ind.mkdir()
            _make_pdfs(ind, 2)
            ws = Path(td) / "ws"
            rc = main(["run", "--in", str(ind), "--workspace", str(ws),
                       "--fake"])
            self.assertEqual(rc, 0)
            # artefactos en el layout canónico
            self.assertTrue((ws / "ocr" / "doc0.txt").exists())
            self.assertTrue((ws / "summaries" / "doc0.json").exists())
            report = json.loads(
                (ws / "summaries" / "report.json").read_text())
            self.assertEqual(report["metrics"]["total"], 2)

    def test_cli_transcribe(self):
        """C7: 'transcribe --fake' solo genera ocr/*.txt."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "pdfs"; ind.mkdir()
            _make_pdfs(ind, 2)
            ws = Path(td) / "ws"
            rc = main(["transcribe", "--in", str(ind), "--workspace",
                       str(ws), "--fake"])
            self.assertEqual(rc, 0)
            self.assertTrue((ws / "ocr" / "doc0.txt").exists())
            self.assertTrue((ws / "ocr" / "doc1.txt").exists())
            # no resume: no hay summaries
            self.assertFalse((ws / "summaries").exists())


if __name__ == "__main__":
    unittest.main()
