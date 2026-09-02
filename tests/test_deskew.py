"""FASE18 C3/C4: estimación de ángulo de deskew (dominio puro)."""

import unittest

from PIL import Image, ImageDraw

from pdfsum.segment import SKEW_MIN_APPLY, estimate_skew


def _text_page(angle: float = 0.0, size=(1000, 1400)) -> Image.Image:
    """Página sintética con 'líneas de texto' horizontales, rotada."""
    img = Image.new("L", size, 255)
    draw = ImageDraw.Draw(img)
    for y in range(150, size[1] - 150, 40):
        # línea de "palabras": segmentos oscuros con huecos
        x = 100
        while x < size[0] - 100:
            w = 60
            draw.rectangle([x, y, x + w, y + 14], fill=20)
            x += w + 18
    if angle:
        img = img.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=255)
    return img


class TestEstimateSkew(unittest.TestCase):
    def test_pagina_recta_no_rota(self):
        """C3: página recta -> ángulo < umbral de aplicación."""
        img = _text_page(0.0)
        angle = estimate_skew(img)
        self.assertLess(abs(angle), SKEW_MIN_APPLY)

    def test_detecta_rotacion_negativa(self):
        """C3: página torcida -1.5° -> estima ~+1.5° (corrección)."""
        img = _text_page(-1.5)
        angle = estimate_skew(img)
        self.assertAlmostEqual(angle, 1.5, delta=0.5)
        self.assertGreaterEqual(abs(angle), SKEW_MIN_APPLY)

    def test_detecta_rotacion_positiva(self):
        img = _text_page(2.0)
        angle = estimate_skew(img)
        self.assertAlmostEqual(angle, -2.0, delta=0.5)

    def test_correccion_endereza(self):
        """Aplicar el ángulo estimado deja la página ~recta."""
        img = _text_page(-1.5)
        angle = estimate_skew(img)
        corrected = img.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=255)
        self.assertLess(abs(estimate_skew(corrected)), SKEW_MIN_APPLY)


if __name__ == "__main__":
    unittest.main()
