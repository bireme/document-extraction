"""Tests para consolidación inteligente de resúmenes (criterio C6)."""
import unittest

from pdfsum.consolidation import consolidate_sections, deduplicate_field


class TestDeduplication(unittest.TestCase):
    """Tests para deduplicación de campos repetibles."""

    def test_deduplicate_field_simple(self):
        """Deduplica valores repetidos en una lista."""
        values = ["- ATP", "- Glucosa", "- ATP", "- Ribosoma"]
        result = deduplicate_field(values)

        # ATP no debe aparecer dos veces
        lines = result.split("\n")
        atp_count = sum(1 for line in lines if "ATP" in line)
        self.assertEqual(atp_count, 1)

        # Debe contener los 3 únicos valores
        self.assertIn("ATP", result)
        self.assertIn("Glucosa", result)
        self.assertIn("Ribosoma", result)

    def test_consolidate_terminos_deduplica(self):
        """C6: consolida varios resúmenes deduplicando terminos."""
        partials = [
            {
                "titulo": "Capítulo 1",
                "terminos": "- ATP\n- Mitocondria\n- Glucosa",
                "publico": "- Estudiantes\n- Doctores",
                "sintesis": "Cap 1 sobre energía",
            },
            {
                "titulo": "Capítulo 2",
                "terminos": "- ATP\n- Glucosa\n- Ribosoma",
                "publico": "- Doctores\n- Enfermeras",
                "sintesis": "Cap 2 sobre síntesis",
            },
        ]

        result = consolidate_sections(partials, dedup_fields=["publico", "terminos"])

        # Verificar que no hay repeticiones en terminos
        terminos_lines = result["terminos"].split("\n")
        atp_count = sum(1 for line in terminos_lines if "ATP" in line)
        self.assertEqual(atp_count, 1, "ATP no debe aparecer duplicado en terminos")

        # Verificar que hay todas las variantes únicas
        self.assertIn("ATP", result["terminos"])
        self.assertIn("Mitocondria", result["terminos"])
        self.assertIn("Ribosoma", result["terminos"])

    def test_consolidate_sintesis_concatena(self):
        """Campos narrativos se concatenan con saltos de párrafo."""
        partials = [
            {
                "sintesis": "Cap 1: introducción a energía celular",
                "terminos": "- ATP",
            },
            {
                "sintesis": "Cap 2: síntesis de proteínas",
                "terminos": "- Ribosoma",
            },
        ]

        result = consolidate_sections(partials)

        # sintesis debe concatenar ambos párrafos
        self.assertIn("Cap 1", result["sintesis"])
        self.assertIn("Cap 2", result["sintesis"])
        # Con doble salto de línea entre ellos
        self.assertIn("\n\n", result["sintesis"])

    def test_consolidate_valores_vacios(self):
        """Ignorar valores vacíos o de solo espacios."""
        partials = [
            {"titulo": "Cap 1", "terminos": "- ATP"},
            {"titulo": "Cap 2", "terminos": "   "},  # solo espacios
            {"titulo": "Cap 3", "terminos": ""},    # vacío
        ]

        result = consolidate_sections(partials)

        # Solo ATP en terminos, sin duplicación de vacíos
        self.assertIn("ATP", result["terminos"])
        # No debe tener múltiples líneas vacías
        lines = [l for l in result["terminos"].split("\n") if l.strip()]
        self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
