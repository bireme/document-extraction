"""Tests del set de control y cobertura (criterios C5, C6, C7, C10)."""
import unittest

from pdfsum.contract import SummaryResult
from pdfsum.control import (
    ControlCase,
    evaluate_case,
    run_control_suite,
    term_coverage,
)


def _res(doc_id, tipo="articulo", idioma="pt", terms_text=""):
    return SummaryResult(
        doc_id=doc_id, idioma_principal=idioma, tipo_documento=tipo,
        plantilla="A",
        secciones={"titulo": "T", "objetivo": terms_text},
    )


class TestControl(unittest.TestCase):
    def test_term_coverage(self):
        """C5: fracción de términos presentes + faltantes."""
        cov, missing = term_coverage(
            "vacina sarampo poliomielite", ["sarampo", "febre", "vacina"])
        self.assertAlmostEqual(cov, 2 / 3, places=3)
        self.assertEqual(missing, ["febre"])
        # sin términos esperados -> cobertura 1.0
        self.assertEqual(term_coverage("x", []), (1.0, []))

    def test_evaluate_case(self):
        """C6: compara resultado vs caso (idioma/tipo/términos)."""
        res = _res("d1", tipo="articulo", idioma="pt",
                   terms_text="estudo sobre sarampo e vacina")
        case = ControlCase(doc_id="d1", expected_lang="pt",
                           expected_type="articulo",
                           expected_terms=["sarampo", "vacina"])
        v = evaluate_case(res, case)
        self.assertTrue(v.passed)
        self.assertEqual(v.coverage, 1.0)
        self.assertTrue(v.lang_ok and v.type_ok)

    def test_control_suite(self):
        """C7: agrega veredictos: cobertura media, aciertos, fallos."""
        res = {
            "d1": _res("d1", "articulo", "pt", "sarampo vacina"),
            "d2": _res("d2", "manual", "en", "health study"),
        }
        cases = [
            ControlCase("d1", "pt", "articulo", ["sarampo", "vacina"]),
            ControlCase("d2", "pt", "manual", ["health", "falta"]),  # falla
        ]
        rep = run_control_suite(res, cases)
        self.assertEqual(rep.total, 2)
        self.assertEqual(rep.passed, 1)          # d1 pasa, d2 no
        self.assertEqual(rep.type_aciertos, 2)   # ambos tipo ok
        self.assertEqual(rep.lang_aciertos, 1)   # d2 idioma en != pt esperado

    def test_suite_sobre_set(self):
        """C10: suite sobre un set con resultados del FakeSummarizer."""
        from pdfsum.adapters.fake_summarizer import FakeSummarizer
        from pdfsum.pipeline import summarize_document
        text = ("RESUMO\nObjetivo: avaliar sarampo. Métodos: estudo. "
                "Resultados: dados. Conclusões: ok.\nPalavras-chave: saúde.\n"
                "ABSTRACT\nObjective: x. Methods: y.\nKeywords: z.\n")
        res = summarize_document("d1", text, FakeSummarizer(), pages=4)
        rep = run_control_suite(
            {"d1": res},
            [ControlCase("d1", expected_type="articulo")],
        )
        self.assertEqual(rep.total, 1)
        self.assertEqual(rep.type_aciertos, 1)
        self.assertIn("verdicts", rep.to_dict())


if __name__ == "__main__":
    unittest.main()
