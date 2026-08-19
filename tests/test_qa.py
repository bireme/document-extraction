"""Tests de QA gates (criterios C1-C5)."""
import unittest

from pdfsum.contract import Abstract, SummaryResult
from pdfsum.qa import QAReport, check_result


def _good() -> SummaryResult:
    return SummaryResult(
        doc_id="d", idioma_principal="pt", tipo_documento="divulgacion",
        plantilla="C",
        secciones={
            "titulo": "Prevenção do tabagismo",
            "tipo_documento": "folheto",
            "entidad": "Ministério da Saúde",
            "publico": "população em geral",
            "resumen_ejecutivo": "O documento trata da importância de não fumar "
                                 "e apresenta o Disque Saúde para apoio.",
            "puntos_clave": "- parar de fumar\n- Disque Saúde",
            "terminos": "tabagismo, cessação",
        },
    )


class TestQA(unittest.TestCase):
    def test_gate_schema(self):
        """C1: secciones obligatorias vacías -> fallo 'schema'."""
        self.assertTrue(check_result(_good()).is_ok)
        bad = _good()
        bad.secciones["resumen_ejecutivo"] = "  "
        rep = check_result(bad)
        self.assertFalse(rep.is_ok)
        self.assertIn("schema", [f.gate for f in rep.failures])

    def test_gate_refusal(self):
        """C2: texto de refusal -> fallo 'refusal'."""
        bad = _good()
        bad.secciones["resumen_ejecutivo"] = "Não posso gerar esse conteúdo."
        rep = check_result(bad)
        self.assertIn("refusal", [f.gate for f in rep.failures])

    def test_gate_language(self):
        """C3: idioma del resumen != idioma_principal -> fallo 'lang'."""
        bad = _good()
        bad.idioma_principal = "en"  # pero el texto está en pt
        rep = check_result(bad)
        self.assertIn("lang", [f.gate for f in rep.failures])

    def test_gate_abstracts(self):
        """C4: abstracts declarados pero no preservados -> fallo 'abstracts'."""
        bad = _good()
        bad.idiomas_resumo_origem = ["pt", "en"]
        bad.abstracts_origem = [Abstract(lang="pt", header="RESUMO", text="x" * 50)]
        rep = check_result(bad)
        self.assertIn("abstracts", [f.gate for f in rep.failures])

    def test_qa_report(self):
        """C5: QAReport agrega passed/failed y is_ok."""
        rep = QAReport(doc_id="d")
        self.assertTrue(rep.is_ok)
        rep.add("schema", "falta X")
        self.assertFalse(rep.is_ok)
        self.assertEqual(rep.to_dict()["failures"][0]["gate"], "schema")


if __name__ == "__main__":
    unittest.main()
