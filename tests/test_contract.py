"""Tests del contrato JSON (criterios C1, C2)."""
import unittest

from pdfsum.contract import Abstract, SummaryResult


def _sample() -> SummaryResult:
    return SummaryResult(
        doc_id="doc1",
        idioma_principal="pt",
        tipo_documento="articulo",
        plantilla="A",
        secciones={"titulo": "T", "objetivo": "O"},
        idiomas_resumo_origem=["pt", "en"],
        abstracts_origem=[
            Abstract(lang="pt", header="RESUMO", text="texto", keywords="k"),
            Abstract(lang="en", header="ABSTRACT", text="text", keywords=""),
        ],
        meta={"pages": 3},
    )


class TestContract(unittest.TestCase):
    def test_summary_result_schema(self):
        """C1: campos obligatorios presentes y serializables a JSON."""
        d = _sample().to_dict()
        for field in ("doc_id", "idioma_principal", "idiomas_resumo_origem",
                      "tipo_documento", "plantilla", "secciones",
                      "abstracts_origem", "meta"):
            self.assertIn(field, d)
        self.assertIsInstance(d["idiomas_resumo_origem"], list)
        self.assertIsInstance(d["secciones"], dict)
        self.assertIsInstance(d["abstracts_origem"], list)
        # serializa sin error
        s = _sample().to_json()
        self.assertIn("\"doc_id\": \"doc1\"", s)

    def test_roundtrip(self):
        """C2: to_json -> from_json produce objeto equivalente."""
        original = _sample()
        restored = SummaryResult.from_json(original.to_json())
        self.assertEqual(restored.to_dict(), original.to_dict())
        self.assertEqual(len(restored.abstracts_origem), 2)
        self.assertEqual(restored.abstracts_origem[0].header, "RESUMO")


if __name__ == "__main__":
    unittest.main()
