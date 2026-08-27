"""Tests del subcomando `pdfsum bibframe` (criterio C5, FASE15)."""

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from pdfsum.cli import main


def _write_summary(dir_: Path, doc_id: str, titulo: str = "Un título") -> None:
    secciones = {"titulo": titulo} if titulo else {}
    d = {
        "doc_id": doc_id,
        "idioma_principal": "es",
        "tipo_documento": "divulgacion",
        "plantilla": "C",
        "secciones": secciones,
        "idiomas_resumo_origem": [],
        "abstracts_origem": [],
        "meta": {"pages": 3},
    }
    (dir_ / f"{doc_id}.json").write_text(
        json.dumps(d, ensure_ascii=False), encoding="utf-8"
    )


class TestCliBibframe(unittest.TestCase):
    def test_un_registro_por_documento(self):
        with TemporaryDirectory() as td:
            sums = Path(td) / "summaries"
            sums.mkdir()
            _write_summary(sums, "doc_a")
            _write_summary(sums, "doc_b")
            # report.json debe ignorarse
            (sums / "report.json").write_text("{}", encoding="utf-8")
            out = Path(td) / "bibframe"

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["bibframe", "--in", str(sums), "--out", str(out)])
            self.assertEqual(rc, 0)
            self.assertIn("generados=2", buf.getvalue())

            files = sorted(p.name for p in out.glob("*.bibframe.json"))
            self.assertEqual(files, ["doc_a.bibframe.json", "doc_b.bibframe.json"])
            rec = json.loads((out / "doc_a.bibframe.json").read_text())
            self.assertEqual(rec["@graph"][0]["@type"], "bf:Work")
            self.assertEqual(rec["_pdfsum"]["doc_id"], "doc_a")

    def test_sin_titulo_se_omite_con_motivo(self):
        with TemporaryDirectory() as td:
            sums = Path(td) / "summaries"
            sums.mkdir()
            _write_summary(sums, "doc_ok")
            _write_summary(sums, "doc_sin_titulo", titulo="")
            out = Path(td) / "bibframe"

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["bibframe", "--in", str(sums), "--out", str(out)])
            self.assertEqual(rc, 0)
            self.assertIn("generados=1", buf.getvalue())
            self.assertIn("omitidos=1", buf.getvalue())

            report = json.loads((out / "bibframe_report.json").read_text())
            self.assertEqual(report["generados"], 1)
            self.assertEqual(report["omitidos"][0]["doc_id"], "doc_sin_titulo")
            self.assertIn("título", report["omitidos"][0]["motivo"])
            self.assertFalse((out / "doc_sin_titulo.bibframe.json").exists())

    def test_pdfs_dir_opcional_inexistente_no_rompe(self):
        with TemporaryDirectory() as td:
            sums = Path(td) / "summaries"
            sums.mkdir()
            _write_summary(sums, "doc_a")
            out = Path(td) / "bibframe"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        "bibframe",
                        "--in",
                        str(sums),
                        "--pdfs",
                        str(Path(td) / "no_existe"),
                        "--out",
                        str(out),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertIn("generados=1", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
