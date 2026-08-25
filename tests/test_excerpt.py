"""Tests de estrategia de porción (criterios C1-C6)."""

import unittest

from pdfsum.contract import DocType
from pdfsum.excerpt import find_structural_sections, select_excerpt

# Artículo largo: abstract + intro + conclusiones + mucho cuerpo.
_ARTICLE = (
    "RESUMO\nEste estudo avalia algo importante sobre saúde pública. " * 20
    + "\n\nINTRODUÇÃO\nO problema de investigação parte de la necesidad. " * 40
    + "\n\nMÉTODOS\n"
    + ("bla metodológico " * 400)
    + "\n\nRESULTADOS\n"
    + ("dado experimental " * 400)
    + "\n\nCONCLUSÕES\nConcluímos que la técnica funciona adecuadamente. " * 20
)

# Manual largo: portada + apresentação + sumário + introdução + cuerpo enorme.
_MANUAL = (
    "MINISTÉRIO DA SAÚDE - Manual de práticas\n\n"
    + "APRESENTAÇÃO\nEste manual apresenta diretrizes fundamentais. " * 15
    + "\n\nSUMÁRIO\n1. Introdução  2. Métodos  3. Anexos\n\n"
    + "INTRODUÇÃO\nO contexto de saúde pública exige diretrizes. " * 20
    + "\n\n"
    + ("conteúdo extenso do corpo do manual " * 2000)
)

_FLYER = "Deixe de fumar. Ligue Disque Saúde. Ministério da Saúde. " * 5

_BUDGET = 4000


class TestExcerpt(unittest.TestCase):
    def test_articulo(self):
        """C1: artículo -> abstract+intro+conclusiones, no cuerpo entero."""
        exc = select_excerpt(_ARTICLE, DocType.ARTICULO, max_chars=_BUDGET)
        self.assertEqual(exc.strategy, "articulo")
        self.assertIn("abstract", exc.parts)
        self.assertIn("conclusao", exc.parts)
        # no debe contener el grueso de "dado experimental" (cuerpo/resultados)
        self.assertLess(exc.text.count("dado experimental"), 50)

    def test_manual(self):
        """C2: manual -> portada+apresentação+sumário+introdução."""
        exc = select_excerpt(_MANUAL, DocType.MANUAL, max_chars=_BUDGET)
        self.assertEqual(exc.strategy, "manual")
        self.assertIn("portada", exc.parts)
        self.assertTrue({"apresentacao", "sumario", "introducao"} & set(exc.parts))

    def test_divulgacion(self):
        """C3: folleto corto -> texto completo."""
        exc = select_excerpt(_FLYER, DocType.DIVULGACION, max_chars=_BUDGET)
        self.assertEqual(exc.strategy, "full")
        self.assertFalse(exc.truncated)

    def test_budget(self):
        """C4: la porción nunca excede el presupuesto y reporta metadatos."""
        for text, dt in (
            (_ARTICLE, DocType.ARTICULO),
            (_MANUAL, DocType.MANUAL),
            (_FLYER, DocType.DIVULGACION),
        ):
            exc = select_excerpt(text, dt, max_chars=_BUDGET)
            self.assertLessEqual(len(exc.text), _BUDGET)
            self.assertIsInstance(exc.parts, list)
            self.assertIsInstance(exc.truncated, bool)

    def test_manual_no_blind_prefix(self):
        """C5: manual largo -> NO es solo los primeros N chars (incluye estruct.)."""
        exc = select_excerpt(_MANUAL, DocType.MANUAL, max_chars=_BUDGET)
        blind_prefix = _MANUAL[:_BUDGET]
        self.assertNotEqual(exc.text, blind_prefix)
        # incluye contenido de una sección estructural más allá del prefijo
        self.assertTrue(
            ("SUMÁRIO" in exc.text)
            or ("INTRODUÇÃO" in exc.text)
            or ("APRESENTAÇÃO" in exc.text)
        )

    def test_structural_sections(self):
        """C6: localiza encabezados estructurales con offsets, en pt."""
        secs = {s.name for s in find_structural_sections(_MANUAL)}
        self.assertIn("apresentacao", secs)
        self.assertIn("sumario", secs)
        self.assertIn("introducao", secs)


if __name__ == "__main__":
    unittest.main()
