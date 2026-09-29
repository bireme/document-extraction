"""Test de la CLI en modo dry-run (criterio C10)."""

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from pdfsum.cli import main


class TestCLI(unittest.TestCase):
    def test_cli_dry_run_json(self):
        """C10: 'summarize --dry-run' produce JSON válido contra el contrato."""
        with TemporaryDirectory() as td:
            txt = Path(td) / "doc.txt"
            txt.write_text(
                "RESUMO\nObjetivo: avaliar. Métodos: estudo. "
                "Resultados: dados. Conclusões: ok.\n"
                "Palavras-chave: saúde.\nABSTRACT\nObjective: assess. "
                "Methods: study. Results: data. Conclusions: ok.\n"
                "Keywords: health.\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["summarize", "--text", str(txt), "--dry-run"])

            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            # contrato
            for f in (
                "doc_id",
                "idioma_principal",
                "tipo_documento",
                "ai_extracted_abstract",
                "ai_generated_abstract",
                "meta",
            ):
                self.assertIn(f, data)
            self.assertEqual(data["tipo_documento"], "articulo")
            self.assertEqual(data["ai_extracted_abstract"], [])
            self.assertTrue(data["ai_generated_abstract"])
            self.assertNotIn("secciones", data)


if __name__ == "__main__":
    unittest.main()
