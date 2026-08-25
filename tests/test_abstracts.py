"""Tests de extracción de abstracts (criterios C6, C7)."""

import unittest

from pdfsum.abstracts import abstract_langs, extract_abstracts

_TRILINGUAL = """
RESUMO: A reorientação da assistência psiquiátrica possibilitou serviços
alternativos e cuidado mais humanizado, analisando a percepção de
profissionais de um CAPS sobre acolhimento.
Palavras-chave: Saúde Mental. Acolhimento.
ABSTRACT: The reorientation of psychiatric assistance made possible
alternative services and more humanized care, analyzing the perception of
professionals of a CAPS about reception.
Keywords: Mental Health. Embracement.
RESUMEN: La reorientación de la asistencia psiquiátrica posibilitó servicios
alternativos y cuidado más humanizado, analizando la percepción de
profesionales de un CAPS sobre la acogida.
"""

_NO_ABSTRACT = "Deixe de fumar. Ligue Disque Saúde. Ministério da Saúde."


class TestAbstracts(unittest.TestCase):
    def test_trilingual(self):
        """C6: RESUMO+ABSTRACT+RESUMEN -> 3 bloques por idioma, verbatim."""
        blocks = extract_abstracts(_TRILINGUAL)
        self.assertEqual([b.lang for b in blocks], ["pt", "en", "es"])
        self.assertEqual(abstract_langs(blocks), ["pt", "en", "es"])
        # verbatim: contiene texto original, no traducido
        pt = blocks[0]
        self.assertIn("reorientação da assistência", pt.text)
        self.assertIn("Saúde Mental", pt.keywords)
        en = blocks[1]
        self.assertIn("reorientation of psychiatric", en.text)

    def test_no_abstract(self):
        """C7: sin bloques de resumen -> lista vacía (no inventa)."""
        self.assertEqual(extract_abstracts(_NO_ABSTRACT), [])
        self.assertEqual(abstract_langs([]), [])


if __name__ == "__main__":
    unittest.main()
