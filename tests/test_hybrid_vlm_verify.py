"""FASE19 C3: reintento y degradación registrada en el adaptador."""

import unittest
from unittest.mock import patch

# TSV de baja confianza (route -> vlm) con palabras reales de contraste.
_HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
    "left\ttop\twidth\theight\tconf\ttext"
)


def _tsv_row(block, line, word_num, conf, text):
    return f"5\t1\t{block}\t1\t{line}\t{word_num}\t0\t0\t10\t10\t{conf}\t{text}"


_WORDS = ["vigilancia", "epidemiológica", "salud", "población", "eventos", "oportuna"]
_TSV_LOW = "\n".join(
    [_HEADER]
    + [_tsv_row(1, 1, i + 1, 40, w) for i, w in enumerate(_WORDS[:3])]
    + [_tsv_row(1, 2, i + 1, 40, w) for i, w in enumerate(_WORDS[3:])]
)

_BUENA = (
    "La vigilancia epidemiológica permite obtener información oportuna "
    "sobre los eventos de salud de la población."
)
_ALUCINADA = (
    "El tratado de Versalles estableció las condiciones de paz tras la "
    "primera guerra mundial en Europa occidental."
)


class _SpyVlm:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def ocr_image(self, path, lang):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _make(vlm):
    from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber

    with patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/x"):
        return HybridOcrTranscriber(lang="spa", vlm=vlm)


def _run_page(tx):
    from pathlib import Path

    with patch("pdfsum.adapters.hybrid_ocr._run", return_value=_TSV_LOW):
        return tx._ocr_page(Path("/fake/region.png"))


class TestReintentoYDegradacion(unittest.TestCase):
    def test_rechazo_y_reintento_aceptado(self):
        """(a) 1º rechazado + 2º bueno -> texto del 2º, sin marca."""
        vlm = _SpyVlm([_ALUCINADA, _BUENA])
        text, _conf, _words, info = _run_page(_make(vlm))
        self.assertEqual(vlm.calls, 2)
        self.assertEqual(text, _BUENA)
        self.assertTrue(info["vlm"])
        self.assertFalse(info["vlm_rejected"])

    def test_doble_rechazo_degrada_a_tesseract(self):
        """(b) 2 rechazos -> texto Tesseract del TSV + marca con motivo."""
        vlm = _SpyVlm([_ALUCINADA, _ALUCINADA])
        text, _conf, _words, info = _run_page(_make(vlm))
        self.assertEqual(vlm.calls, 2)
        self.assertTrue(info["vlm_rejected"])
        self.assertIn("solape", info["motivo"])
        self.assertFalse(info["vlm"])
        # el texto degradado es el que Tesseract leyó (líneas del TSV)
        self.assertIn("vigilancia epidemiológica salud", text)
        self.assertIn("población eventos oportuna", text)

    def test_excepcion_y_vacio_cuentan_como_rechazo(self):
        """(c) excepción y "" -> degradación registrada, nunca "" mudo."""
        vlm = _SpyVlm([RuntimeError("ollama caído"), ""])
        text, _conf, _words, info = _run_page(_make(vlm))
        self.assertTrue(info["vlm_rejected"])
        self.assertEqual(info["motivo"], "vacio")
        self.assertTrue(text.strip())  # texto Tesseract, no vacío

    def test_primera_buena_no_reintenta(self):
        vlm = _SpyVlm([_BUENA])
        text, _conf, _words, _info = _run_page(_make(vlm))
        self.assertEqual(vlm.calls, 1)
        self.assertEqual(text, _BUENA)


if __name__ == "__main__":
    unittest.main()
