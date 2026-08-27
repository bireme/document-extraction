"""Tests de adapters/llm_prompt.py (criterio C2, FASE14)."""

import unittest

from pdfsum.adapters.llm_prompt import build_prompt, parse_sections, strip_think


class TestLlmPrompt(unittest.TestCase):
    def test_build_prompt_incluye_instruccion_esquema_y_texto(self):
        p = build_prompt("mi texto", lang="es", template="C", max_chars=1000)
        self.assertIn("sistema automático de catalogación", p)
        self.assertIn("## Título", p)
        self.assertIn("mi texto", p)

    def test_build_prompt_recorta_a_max_chars(self):
        p = build_prompt("x" * 100, lang="en", template="C", max_chars=10)
        self.assertIn("x" * 10, p)
        self.assertNotIn("x" * 11, p)

    def test_build_prompt_lang_desconocido_usa_pt(self):
        p_pt = build_prompt("t", lang="pt", template="C", max_chars=100)
        p_xx = build_prompt("t", lang="xx", template="C", max_chars=100)
        self.assertEqual(p_pt.split("\n\n")[0], p_xx.split("\n\n")[0])

    def test_strip_think(self):
        raw = "antes <think>razonando...</think> despues"
        self.assertEqual(strip_think(raw), "antes  despues")

    def test_parse_sections_roundtrip(self):
        md = "## Título\nMi título\n\n## Tipo de documento\nfolleto\n"
        out = parse_sections(md, template="C", lang="es")
        self.assertEqual(out["titulo"], "Mi título")
        self.assertEqual(out["tipo_documento"], "folleto")

    def test_parse_sections_vacio(self):
        self.assertEqual(parse_sections("", template="C", lang="es"), {})


if __name__ == "__main__":
    unittest.main()
