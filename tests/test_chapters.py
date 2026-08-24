"""Tests para detección de capítulos (criterios C1-C7)."""
import unittest

from pdfsum.chapters import detect_chapters, verify_coverage


class TestChapters(unittest.TestCase):
    """Unit tests para chapters.py."""

    def test_detect_chapters_crisis(self):
        """C1: Detectar los 13 capítulos correctos de crisis_familianuevo."""
        with open("data/ocr/crisis_familianuevo.txt", encoding="utf-8",
                  errors="replace") as f:
            text = f.read()

        chapters = detect_chapters(text, lang="es")

        # Debe detectar exactamente 13 capítulos
        self.assertEqual(len(chapters), 13)

        # Verificar número y títulos en orden
        expected_titles = [
            "CRISIS, NECESIDAD Y ESTRÉS",
            "CRISIS Y ENFERMEDAD: TRASTORNOS",
            "CRISIS Y PSICOTERAPIA",
            "LO SISTÉMICO Y LO REPRODUCTIVO",
            "CRISIS Y SALUD FAMILIAR",
            "FUNCIONALIDAD Y TRASTORNO FAMILIAR",
            "SALUD MENTAL FAMILIAR",
            "PSICOTERAPIA. GENERALIDADES",
            "LA ESCUELA CUBANA DE PSICOTERAPIA",
            "PSICOTERAPIA CONCRETA PROFUNDA",
            "PSICOTERAPIA CONCRETA BREVE",
            "PSICOTERAPIA CONCRETA GRUPAL",
            "PSICOTERAPIA FAMILIAR",
        ]
        for i, ch in enumerate(chapters):
            self.assertEqual(ch.number, str(i + 1))
            self.assertIn(expected_titles[i], ch.title)

    def test_chapters_cobertura_total(self):
        """C2: Cobertura total — concatenar chapters debe igualar original."""
        with open("data/ocr/crisis_familianuevo.txt", encoding="utf-8",
                  errors="replace") as f:
            text = f.read()

        chapters = detect_chapters(text, lang="es")
        self.assertTrue(verify_coverage(text, chapters))

    def test_fallback_no_capitulos(self):
        """C3: Sin capítulos, detect_chapters() retorna []."""
        # Texto sin capítulos
        text = "Este es un texto sin capítulos. Solo párrafos soltos."
        chapters = detect_chapters(text)
        self.assertEqual(len(chapters), 0)

    def test_chapters_son_disjuntos(self):
        """Capítulos no solapan y juntos cubren todo."""
        with open("data/ocr/crisis_familianuevo.txt", encoding="utf-8",
                  errors="replace") as f:
            text = f.read()

        chapters = detect_chapters(text)
        for i in range(len(chapters) - 1):
            ch1 = chapters[i]
            ch2 = chapters[i + 1]
            # No solapan: fin de ch1 no aparece en inicio de ch2
            self.assertNotIn(ch1.text[-10:], ch2.text)

    def test_no_perdida_capitulos(self):
        """Cada capítulo tiene contenido (text no vacío)."""
        with open("data/ocr/crisis_familianuevo.txt", encoding="utf-8",
                  errors="replace") as f:
            text = f.read()

        chapters = detect_chapters(text)
        for ch in chapters:
            msg = f"Capítulo {ch.number} muy vacío: {len(ch.text)} chars"
            self.assertGreater(len(ch.text), 100, msg)



if __name__ == "__main__":
    unittest.main()
