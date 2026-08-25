"""Tests de segmentación de página (criterios C1-C4)."""

import unittest

from PIL import Image, ImageDraw

from pdfsum.segment import (
    detect_columns,
    detect_regions,
    sort_reading_order,
    valid_regions,
)


def _img_2cols() -> Image.Image:
    img = Image.new("L", (800, 600), 255)
    d = ImageDraw.Draw(img)
    # columna izq: dos párrafos (bloques)
    for y in range(50, 300, 18):
        d.rectangle([80, y, 340, y + 10], fill=0)
    for y in range(360, 550, 18):
        d.rectangle([80, y, 340, y + 10], fill=0)
    # columna der: un párrafo
    for y in range(50, 500, 18):
        d.rectangle([460, y, 720, y + 10], fill=0)
    return img


def _img_1col() -> Image.Image:
    img = Image.new("L", (400, 300), 255)
    d = ImageDraw.Draw(img)
    for y in range(20, 280, 20):
        d.rectangle([40, y, 360, y + 10], fill=0)
    return img


class TestSegment(unittest.TestCase):
    def test_detect_columns(self):
        """C1: 2 columnas -> 2 regiones; 1 columna -> 1."""
        self.assertEqual(len(detect_columns(_img_2cols())), 2)
        self.assertEqual(len(detect_columns(_img_1col())), 1)

    def test_regions_validas(self):
        """C2: sin área cero, sin duplicados, dentro de la imagen."""
        img = _img_2cols()
        regs = valid_regions(detect_regions(img), *img.size)
        for r in regs:
            self.assertGreater(r.area(), 0)
            self.assertTrue(0 <= r.left < r.right <= img.width)
            self.assertTrue(0 <= r.top < r.bottom <= img.height)
        keys = [(r.left, r.top, r.right, r.bottom) for r in regs]
        self.assertEqual(len(keys), len(set(keys)))

    def test_reading_order(self):
        """C3: orden de lectura izq->der, arriba->abajo."""
        from itertools import pairwise

        regs = sort_reading_order(detect_regions(_img_2cols()))
        for a, b in pairwise(regs):
            self.assertTrue((a.left < b.left) or (a.left == b.left and a.top <= b.top))

    def test_cobertura(self):
        """C4: multicolumna -> >1 región y cubre el contenido."""
        img = _img_2cols()
        regs = detect_regions(img)
        self.assertGreater(len(regs), 1)
        # las 3 zonas de texto generan 3 bloques
        self.assertEqual(len(valid_regions(regs, *img.size)), 3)


if __name__ == "__main__":
    unittest.main()
