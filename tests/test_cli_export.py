"""Test del subcomando export (criterio C11)."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pdfsum.cli import main


def _write_summary(d: Path, doc_id: str) -> None:
    (d / f"{doc_id}.json").write_text(json.dumps({
        "doc_id": doc_id, "idioma_principal": "pt", "tipo_documento": "articulo",
        "plantilla": "A",
        "secciones": {"titulo": "Título X", "objetivo": "Avaliar algo.",
                      "palabras_clave": "Saúde Bucal, Odontologia"},
        "idiomas_resumo_origem": ["pt"],
        "abstracts_origem": [{"lang": "pt", "header": "RESUMO",
                              "text": "Resumo.", "keywords": ""}],
        "meta": {}, "_qa": {"passed": True, "failures": []},
    }), encoding="utf-8")


class TestCLIExport(unittest.TestCase):
    def test_cli_export(self):
        """C11: export genera registros LILACS borrador de todo el lote."""
        with TemporaryDirectory() as td:
            batch = Path(td) / "lote"
            batch.mkdir()
            _write_summary(batch, "art1")
            _write_summary(batch, "art2")
            # ruido que debe ignorarse
            (batch / "report.json").write_text("{}", encoding="utf-8")
            (batch / "_jobs.json").write_text("{}", encoding="utf-8")

            out = Path(td) / "lilacs.json"
            rc = main(["export", "--in", str(batch), "--out", str(out)])
            self.assertEqual(rc, 0)

            records = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(records), 2)
            for rec in records:
                self.assertEqual(rec["status"], "draft")
                self.assertIn("05_tipo_documento", rec["lilacs"])
                self.assertIn("DeCS", rec["_note"])


if __name__ == "__main__":
    unittest.main()
