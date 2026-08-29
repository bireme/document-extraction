"""Tests de segmentación de página (criterios C1-C4)."""

import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from pdfsum.segment import (
    Region,
    _content_mask,
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


def _img_tabla_grafico() -> Image.Image:
    """Página sintética con tabla, ejes y barras oscuras."""
    img = Image.new("L", (900, 700), 255)
    draw = ImageDraw.Draw(img)
    for x in range(80, 821, 148):
        draw.line((x, 80, x, 360), fill=0, width=3)
    for y in range(80, 361, 56):
        draw.line((80, y, 820, y), fill=0, width=3)
    draw.line((100, 620, 820, 620), fill=0, width=4)
    draw.line((100, 420, 100, 620), fill=0, width=4)
    for x, height in ((180, 80), (330, 150), (480, 110), (630, 180)):
        draw.rectangle((x, 620 - height, x + 70, 620), fill=0)
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

    def test_equivalencia_con_segmentacion_anterior(self):
        """Las cajas quedan cerca de la referencia previa, sin perder bloques."""
        reference = [
            Region(40, 25, 400, 327),
            Region(40, 327, 400, 575),
            Region(400, 25, 760, 546),
        ]
        regions = detect_regions(_img_2cols())
        self.assertEqual(len(regions), len(reference))
        for current, previous in zip(regions, reference):
            deltas = (
                abs(current.left - previous.left),
                abs(current.top - previous.top),
                abs(current.right - previous.right),
                abs(current.bottom - previous.bottom),
            )
            self.assertLessEqual(max(deltas), 9)

    def test_pagina_vacia(self):
        """Una página vacía conserva la caja completa como fallback seguro."""
        img = Image.new("L", (640, 480), 255)
        self.assertEqual(detect_regions(img), [Region(0, 0, 640, 480)])

    def test_tabla_y_grafico_no_fallan(self):
        """Las líneas largas y figuras densas no provocan excepciones."""
        img = _img_tabla_grafico()
        regs = valid_regions(detect_regions(img), *img.size)
        self.assertTrue(regs)

    def test_proyeccion_a_resolucion_original(self):
        """Las cajas proyectadas son válidas y no cortan el contenido."""
        img = Image.new("L", (1003, 797), 255)
        draw = ImageDraw.Draw(img)
        draw.rectangle((123, 117, 881, 663), fill=0)
        regs = valid_regions(detect_regions(img), *img.size)
        self.assertTrue(regs)
        self.assertTrue(
            any(
                region.left <= 123
                and region.top <= 117
                and region.right >= 882
                and region.bottom >= 664
                for region in regs
            )
        )

    def test_mascara_reducida_y_reutilizada(self):
        """La segmentación usa una sola máscara al 25 por ciento."""
        img = _img_2cols()
        mask = _content_mask(img)
        self.assertEqual(mask.image.size, (200, 150))
        mask.image.close()
        with patch(
            "pdfsum.segment._content_mask", wraps=_content_mask
        ) as content_mask:
            detect_regions(img)
        content_mask.assert_called_once_with(img)

    def test_instrumentacion_y_rendimiento(self):
        """La página grande expone tiempos y segmenta sin loops por píxel."""
        img = Image.new("L", (2542, 5100), 255)
        draw = ImageDraw.Draw(img)
        for y in range(200, 4700, 45):
            draw.rectangle((180, y, 1120, y + 18), fill=0)
            draw.rectangle((1420, y, 2360, y + 18), fill=0)
        timings: dict[str, float] = {}
        started = time.perf_counter()
        detect_regions(img, timings=timings)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0)
        self.assertEqual(
            set(timings),
            {
                "mascara_segundos",
                "columnas_segundos",
                "regiones_segundos",
                "segmentacion_segundos",
            },
        )
        self.assertTrue(all(value >= 0 for value in timings.values()))


if __name__ == "__main__":
    unittest.main()
