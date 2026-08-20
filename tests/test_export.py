"""Tests del export LILACS (criterios C4, C5, C6)."""
import unittest

from pdfsum.contract import Abstract, SummaryResult
from pdfsum.export import to_lilacs


def _article() -> SummaryResult:
    return SummaryResult(
        doc_id="art1", idioma_principal="pt", tipo_documento="articulo",
        plantilla="A",
        secciones={
            "titulo": "Avaliação do tratamento restaurador atraumático",
            "objetivo": "Avaliar o conhecimento sobre ART.",
            "metodos": "Estudo transversal.",
            "resultados": "Boa conduta.",
            "conclusiones": "Necessita aprimoramento.",
            "palabras_clave": "Cárie Dentária, Odontologia, Saúde Bucal",
        },
        idiomas_resumo_origem=["pt", "en"],
        abstracts_origem=[
            Abstract(lang="pt", header="RESUMO", text="Resumo em português."),
            Abstract(lang="en", header="ABSTRACT", text="Abstract in English."),
        ],
    )


class TestExport(unittest.TestCase):
    def test_lilacs_fields(self):
        """C4: mapea a campos LILACS y marca draft."""
        rec = to_lilacs(_article())
        self.assertEqual(rec["status"], "draft")
        lil = rec["lilacs"]
        self.assertEqual(lil["05_tipo_documento"], "S")  # artigo serial
        self.assertIn("atraumático", lil["titulo"])
        self.assertEqual(lil["idioma_texto"], "pt")
        self.assertTrue(lil["resumos"])

    def test_lilacs_multilingue(self):
        """C5: incluye idioma y adjunta abstracts de origen por idioma."""
        rec = to_lilacs(_article())
        resumos = rec["lilacs"]["resumos"]
        langs = {r["lang"] for r in resumos}
        self.assertIn("pt", langs)
        self.assertIn("en", langs)
        # hay uno generado + los de origen
        sources = {r["source"] for r in resumos}
        self.assertEqual(sources, {"generated", "origin"})
        self.assertEqual(rec["lilacs"]["idiomas_resumo_origem"], ["pt", "en"])

    def test_descriptores_candidatos(self):
        """C6: términos técnicos -> descriptores CANDIDATOS (no validados)."""
        rec = to_lilacs(_article())
        desc = rec["lilacs"]["descritores_candidatos"]
        self.assertIn("Cárie Dentária", desc)
        self.assertIn("Saúde Bucal", desc)
        self.assertIn("candidatos", str(rec["_note"]).lower())
        self.assertIn("DeCS", rec["_note"])


if __name__ == "__main__":
    unittest.main()
