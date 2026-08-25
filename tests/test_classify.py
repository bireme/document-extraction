"""Tests de clasificación (criterios C3, C4, C5)."""

import unittest

from pdfsum.classify import (
    classify_source,
    classify_type,
    detect_language,
    template_for,
)
from pdfsum.contract import DocType, SourceKind

_ARTICLE = """
RESUMO
Objetivo: avaliar algo. Métodos: estudo transversal. Resultados: dados.
Conclusões: funciona.
Palavras-chave: saúde, avaliação.
ABSTRACT
Objective: to assess. Methods: cross-sectional. Results: data.
Conclusions: works.
Keywords: health.
"""

_MANUAL = (
    "SUMÁRIO\nApresentação\n1. Introdução\n2. Métodos\n" + "conteúdo do manual. " * 50
)

_FLYER = "Deixe de fumar. Ligue Disque Saúde. Ministério da Saúde."


class TestClassify(unittest.TestCase):
    def test_source_kind(self):
        """C3: nativo si >=100 chars/pág, escaneado si <100."""
        self.assertEqual(classify_source(500, 3), SourceKind.NATIVO)
        self.assertEqual(classify_source(50, 3), SourceKind.ESCANEADO)
        self.assertEqual(classify_source(0, 0), SourceKind.ESCANEADO)
        # umbral configurable
        self.assertEqual(classify_source(90, 1, threshold=80), SourceKind.NATIVO)

    def test_language(self):
        """C4: distingue pt/es/en; unknown con vacío."""
        self.assertEqual(
            detect_language("O paciente não está com a doença, também é saúde."), "pt"
        )
        self.assertEqual(
            detect_language("El paciente no está con la enfermedad, también es salud."),
            "es",
        )
        self.assertEqual(
            detect_language("The patient has the disease and the study results."), "en"
        )
        self.assertEqual(detect_language(""), "unknown")

    def test_doc_type_and_template(self):
        """C5: reconoce articulo/manual/divulgacion y su plantilla."""
        self.assertEqual(classify_type(_ARTICLE), DocType.ARTICULO)
        self.assertEqual(template_for(DocType.ARTICULO), "A")

        self.assertEqual(classify_type(_MANUAL, pages=20), DocType.MANUAL)
        self.assertEqual(template_for(DocType.MANUAL), "B")

        self.assertEqual(classify_type(_FLYER, pages=1), DocType.DIVULGACION)
        self.assertEqual(template_for(DocType.DIVULGACION), "C")


if __name__ == "__main__":
    unittest.main()
