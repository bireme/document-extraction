"""FASE19 C2: checks de verificación de la salida VLM (dominio puro)."""

import unittest

from pdfsum.vlm_verify import (
    OVERLAP_MIN,
    expected_langs,
    lexical_overlap,
    verify_vlm_output,
)

# Palabras que Tesseract leyó en la región (base de contraste).
_BASE = ["vigilancia", "epidemiológica", "salud", "población", "eventos", "oportuna"]

# Transcripción VLM buena: contiene las palabras base.
_BUENA = (
    "La vigilancia epidemiológica permite obtener información oportuna "
    "sobre los eventos de salud de la población y sus determinantes."
)


class TestChecks(unittest.TestCase):
    def test_vacio_rechaza(self):
        v = verify_vlm_output("", _BASE, "por+eng+spa")
        self.assertFalse(v.accepted)
        self.assertEqual(v.reason, "vacio")
        v = verify_vlm_output("   \n ", _BASE, "por+eng+spa")
        self.assertFalse(v.accepted)

    def test_chachara_rechaza(self):
        for texto in (
            "A imagem mostra um documento antigo com texto em português.",
            "La imagen muestra una página de un manual de salud.",
            "The image shows a scanned document with two columns.",
            "Lo siento, no puedo transcribir esta imagen.",
        ):
            v = verify_vlm_output(texto, _BASE, "por+eng+spa")
            self.assertFalse(v.accepted, texto)
            self.assertIn("chachara", v.reason)

    def test_sin_solape_rechaza(self):
        alucinacion = (
            "El tratado de Versalles estableció las condiciones de paz "
            "tras la primera guerra mundial en Europa occidental."
        )
        v = verify_vlm_output(alucinacion, _BASE, "por+eng+spa")
        self.assertFalse(v.accepted)
        self.assertIn("solape", v.reason)

    def test_idioma_ajeno_rechaza(self):
        frances = (
            "La santé publique est une discipline qui étudie la santé de la "
            "population pour protéger et améliorer le bien-être des personnes. "
        ) * 3
        # base insuficiente para juzgar solape (evita rechazo previo)
        v = verify_vlm_output(frances, [], "por+eng+spa")
        self.assertFalse(v.accepted)
        self.assertIn("idioma", v.reason)

    def test_explosion_rechaza(self):
        rambling = "palabras inventadas del modelo sin ninguna base real " * 80
        v = verify_vlm_output(rambling, ["ruido"], "por+eng+spa")
        self.assertFalse(v.accepted)
        self.assertIn("explosion", v.reason)

    def test_transcripcion_buena_aceptada_verbatim(self):
        v = verify_vlm_output(_BUENA, _BASE, "por+eng+spa")
        self.assertTrue(v.accepted, v.reason)

    def test_sin_base_no_juzga_solape(self):
        """< 5 palabras útiles de Tesseract: sin evidencia, acepta."""
        v = verify_vlm_output("Título breve de la portada", ["xx", "yz"], "por+eng+spa")
        self.assertTrue(v.accepted)

    def test_solape_robusto_a_acentos_y_caja(self):
        base = ["Epidemiológica", "POBLACIÓN", "vigilancia", "salud", "eventos"]
        texto = "la vigilancia epidemiologica de la poblacion y su salud y eventos"
        self.assertGreaterEqual(lexical_overlap(texto, base), OVERLAP_MIN)

    def test_expected_langs(self):
        self.assertEqual(expected_langs("por+eng+spa"), {"pt", "en", "es"})
        self.assertEqual(expected_langs("por"), {"pt"})


if __name__ == "__main__":
    unittest.main()
