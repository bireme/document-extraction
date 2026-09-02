"""FASE16 C2: gates de transcript detectan transcripts degradados."""

import unittest

from pdfsum.transcript_qa import check_transcript, garbage_ratio

# Texto legible real (es), suficiente para superar MIN_TOKENS.
_LEGIBLE_ES = (
    "La salud pública es una disciplina que estudia la salud de la "
    "población para proteger y mejorar el bienestar de las personas. "
    "Este manual presenta los métodos de vigilancia epidemiológica y "
    "las estrategias de prevención que se aplican en los servicios de "
    "salud, con resultados verificados en los estudios más recientes. "
) * 4

_LEGIBLE_PT = (
    "A saúde pública é uma disciplina que estuda a saúde da população "
    "para proteger e melhorar o bem-estar das pessoas. Este manual "
    "apresenta os métodos de vigilância epidemiológica e as estratégias "
    "de prevenção que são aplicadas nos serviços de saúde. "
) * 4

# Basura OCR típica: símbolos fuera del alfabeto esperado.
_GARBAGE = ("₪≈₩ ▓▒░ ø∏∑ ☒☒ ∫∂µ ¥₽ " * 40).strip()


class TestGateGarbage(unittest.TestCase):
    def test_texto_basura_dispara_error(self):
        rep = check_transcript(_GARBAGE, doc_id="d1")
        gates = [f.gate for f in rep.failures]
        self.assertIn("garbage", gates)
        self.assertFalse(rep.is_ok)

    def test_texto_legible_no_dispara(self):
        for texto in (_LEGIBLE_ES, _LEGIBLE_PT):
            rep = check_transcript(texto)
            self.assertEqual(rep.failures, [], rep.to_dict())
            self.assertTrue(rep.is_ok)

    def test_texto_corto_no_juzga(self):
        """Menos de MIN_TOKENS: sin veredicto (evita falsos positivos)."""
        rep = check_transcript("☒☒☒ poco texto")
        self.assertEqual(rep.failures, [])

    def test_marcadores_de_pagina_no_cuentan_como_basura(self):
        texto = "\n".join(f"=== pág {i} ===\n{_LEGIBLE_ES}" for i in range(1, 4))
        self.assertLess(garbage_ratio(texto), 0.05)


class TestGateStopwords(unittest.TestCase):
    def test_ruido_alfabetico_dispara_warning(self):
        # Letras válidas pero sin idioma (OCR ilegible tras deskew fallido).
        ruido = "xkcd qwzx ptkl mnbv " * 40
        rep = check_transcript(ruido)
        gates = {f.gate: f.severity for f in rep.failures}
        self.assertEqual(gates.get("stopword_ratio"), "warning")
        self.assertTrue(rep.is_ok)  # warning no invalida


class TestGatesConMeta(unittest.TestCase):
    def _meta(self, pages_detail=None, quality=None, legacy=False):
        meta = {
            "pages_detail": pages_detail or [],
            "quality": quality or {},
        }
        if legacy:
            meta["legacy"] = True
        return meta

    def test_paginas_vacias_warning_y_error(self):
        detail = [
            {"page": i, "source": "tesseract", "chars": 100} for i in range(1, 10)
        ]
        detail.append({"page": 10, "source": "sin_imagen", "chars": 0})
        rep = check_transcript(_LEGIBLE_ES, self._meta(pages_detail=detail))
        gates = {f.gate: f.severity for f in rep.failures}
        self.assertEqual(gates.get("paginas"), "warning")  # 1/10 = 10% <= 20%

        detail_mal = [
            {"page": i, "source": "tesseract", "chars": 0 if i <= 4 else 100}
            for i in range(1, 11)
        ]
        rep = check_transcript(_LEGIBLE_ES, self._meta(pages_detail=detail_mal))
        gates = {f.gate: f.severity for f in rep.failures}
        self.assertEqual(gates.get("paginas"), "error")  # 4/10 = 40% > 20%
        self.assertFalse(rep.is_ok)

    def test_conf_baja_warning(self):
        rep = check_transcript(_LEGIBLE_ES, self._meta(quality={"conf_media": 41.5}))
        gates = {f.gate: f.severity for f in rep.failures}
        self.assertEqual(gates.get("conf_baja"), "warning")

    def test_conf_alta_sin_fallos(self):
        rep = check_transcript(_LEGIBLE_ES, self._meta(quality={"conf_media": 88.0}))
        self.assertEqual(rep.failures, [])

    def test_legacy_cache_warning(self):
        rep = check_transcript(_LEGIBLE_ES, self._meta(legacy=True))
        gates = {f.gate: f.severity for f in rep.failures}
        self.assertEqual(gates.get("legacy_cache"), "warning")

    def test_sin_meta_solo_gates_de_texto(self):
        rep = check_transcript(_LEGIBLE_ES, None)
        self.assertEqual(rep.failures, [])


if __name__ == "__main__":
    unittest.main()
