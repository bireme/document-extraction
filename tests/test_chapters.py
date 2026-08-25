"""Tests para detección de capítulos (criterios C1-C7)."""
import unittest

from pdfsum.chapters import detect_chapters, verify_coverage


class TestChapters(unittest.TestCase):
    """Unit tests para chapters.py."""

    def test_detect_chapters_simple(self):
        """C1: Detectar capítulos en texto simple."""
        text = (
            "Prefacio: introducción.\n\n"
            "Capítulo\n\n1\n\nTÍTULO PRIMERO\n"
            + "Contenido del cap 1. " * 100
            + "\n\nCapítulo\n\n2\n\nTÍTULO SEGUNDO\n"
            + "Contenido del cap 2. " * 100
            + "\n\nCapítulo\n\n3\n\nTÍTULO TERCERO\n"
            + "Contenido del cap 3. " * 100
        )
        chapters = detect_chapters(text, lang="es")
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[0].number, "1")
        self.assertIn("PRIMERO", chapters[0].title)

    def test_chapters_cobertura_total(self):
        """C2: Cobertura total — capítulos cubren al menos 80%."""
        text = (
            "Intro breve." * 10
            + "\n\nCapítulo\n\n1\n\nCONTENIDO\n"
            + "Contenido. " * 500
            + "\n\nCapítulo\n\n2\n\nOTRO\n"
            + "Más. " * 500
        )
        chapters = detect_chapters(text, lang="es")
        self.assertEqual(len(chapters), 2)
        self.assertTrue(verify_coverage(text, chapters))

    def test_fallback_no_capitulos(self):
        """C3: Sin capítulos, detect_chapters() retorna []."""
        text = "Este es un texto sin capítulos. Solo párrafos soltos."
        chapters = detect_chapters(text)
        self.assertEqual(len(chapters), 0)

    def test_chapters_son_disjuntos(self):
        """Capítulos no solapan."""
        text = (
            "Capítulo\n\n1\n\nPRIMER CAPITULO\n" + "Ca1. " * 100
            + "\n\nCapítulo\n\n2\n\nSEGUNDO CAPITULO\n" + "Ca2. " * 100
        )
        chapters = detect_chapters(text)
        self.assertEqual(len(chapters), 2)

    def test_no_perdida_capitulos(self):
        """Cada capítulo tiene contenido."""
        text = (
            "Capítulo\n\n1\n\nA\n" + "Content. " * 100
            + "\n\nCapítulo\n\n2\n\nB\n" + "More. " * 100
        )
        chapters = detect_chapters(text)
        for ch in chapters:
            self.assertGreater(len(ch.text), 50)



if __name__ == "__main__":
    unittest.main()
