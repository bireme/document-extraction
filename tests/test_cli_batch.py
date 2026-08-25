"""Test de integración del subcomando batch (criterio C11)."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pdfsum.cli import main

_ARTICLE = (
    "RESUMO\nObjetivo: avaliar. Métodos: estudo. Resultados: dados. "
    "Conclusões: ok.\nPalavras-chave: saúde.\n"
    "ABSTRACT\nObjective: assess. Methods: study. Results: data.\n"
    "Keywords: health.\n"
)
_FLYER = "Deixe de fumar. Ligue Disque Saúde. Ministério da Saúde. " * 4


class TestCLIBatch(unittest.TestCase):
    def test_cli_batch_dry_run(self):
        """C11: batch procesa varios .txt, escribe json+report, idempotente."""
        with TemporaryDirectory() as td:
            ind = Path(td) / "in"
            outd = Path(td) / "out"
            ind.mkdir()
            (ind / "art.txt").write_text(_ARTICLE, encoding="utf-8")
            (ind / "fly.txt").write_text(_FLYER, encoding="utf-8")

            rc = main(["batch", "--in", str(ind), "--out", str(outd), "--dry-run"])
            self.assertEqual(rc, 0)

            # un json por doc + report + estado de cola
            self.assertTrue((outd / "art.json").exists())
            self.assertTrue((outd / "fly.json").exists())
            self.assertTrue((outd / "report.json").exists())
            self.assertTrue((outd / "_jobs.json").exists())

            report = json.loads((outd / "report.json").read_text())
            self.assertEqual(report["metrics"]["total"], 2)
            # el artículo debe clasificarse como tal
            tipos = {d["doc_id"]: d["tipo"] for d in report["documents"]}
            self.assertEqual(tipos["art"], "articulo")
            # cada doc lleva su bloque _qa
            art = json.loads((outd / "art.json").read_text())
            self.assertIn("_qa", art)

            # idempotencia: re-ejecutar no reprocesa (cola queda 'done')
            rc2 = main(["batch", "--in", str(ind), "--out", str(outd), "--dry-run"])
            self.assertEqual(rc2, 0)
            counts = json.loads((outd / "report.json").read_text())["queue"]
            self.assertEqual(counts.get("done", 0), 2)


if __name__ == "__main__":
    unittest.main()
