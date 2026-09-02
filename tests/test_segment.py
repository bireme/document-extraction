"""Tests de segmentación de página (criterios C1-C4)."""

import unittest
from random import Random
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
    def _assert_invariants(self, image, regions):
        """Comprueba límites, área, unicidad y orden determinista."""
        coordinates = [
            (region.left, region.top, region.right, region.bottom) for region in regions
        ]
        self.assertEqual(len(coordinates), len(set(coordinates)))
        self.assertEqual(regions, sort_reading_order(regions))
        for region in regions:
            self.assertLessEqual(0, region.left)
            self.assertLess(region.left, region.right)
            self.assertLessEqual(region.right, image.width)
            self.assertLessEqual(0, region.top)
            self.assertLess(region.top, region.bottom)
            self.assertLessEqual(region.bottom, image.height)

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

    def test_reading_order_tolerante_a_bordes_desiguales(self):
        """FASE18 C5: misma columna con bordes izq. desiguales (± medio
        gutter) se lee arriba->abajo; el orden estricto (left, top)
        fallaba este caso."""
        from pdfsum.segment import Region

        misma_col_abajo = Region(100, 300, 300, 400)  # left menor, más abajo
        misma_col_arriba = Region(112, 100, 300, 200)  # left mayor, arriba
        otra_col = Region(500, 100, 700, 400)
        orden = sort_reading_order([misma_col_abajo, otra_col, misma_col_arriba])
        self.assertEqual(orden, [misma_col_arriba, misma_col_abajo, otra_col])
        # el orden estricto anterior habría dado [abajo, arriba, otra] (mal)
        estricto = sorted(
            [misma_col_abajo, otra_col, misma_col_arriba],
            key=lambda r: (r.left, r.top),
        )
        self.assertNotEqual(orden, estricto)

    def test_reading_order_una_columna_intacto(self):
        """FASE18 C5: una sola columna conserva el orden arriba->abajo."""
        from pdfsum.segment import Region

        regs = [Region(100, i * 100, 500, i * 100 + 80) for i in range(4)]
        self.assertEqual(sort_reading_order(list(reversed(regs))), regs)

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

    def test_dimensiones_extremas_impares_y_minimas(self):
        """Páginas anchas, altas, impares y 1x1 conservan cajas válidas."""
        sizes = ((2001, 51), (51, 2001), (1003, 797), (1, 1))
        for width, height in sizes:
            with self.subTest(size=(width, height)):
                image = Image.new("L", (width, height), 255)
                if width > 1 and height > 1:
                    ImageDraw.Draw(image).rectangle(
                        (0, 0, max(0, width - 1), max(0, height - 1)), fill=30
                    )
                regions = detect_regions(image)
                self.assertTrue(regions)
                self._assert_invariants(image, regions)

    def test_bordes_regiones_cercanas_y_fondo_gris(self):
        """Contenido en bordes y bloques vecinos no producen cajas inválidas."""
        image = Image.new("L", (401, 303), 220)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 180, 70), fill=20)
        draw.rectangle((0, 76, 180, 145), fill=20)
        draw.rectangle((220, 0, 400, 145), fill=20)
        regions = detect_regions(image)
        self.assertTrue(regions)
        self._assert_invariants(image, regions)

    def test_ruido_aleatorio_es_determinista(self):
        """Una máscara con ruido fijo siempre produce la misma segmentación."""
        random = Random(20260829)
        image = Image.new("L", (257, 193), 230)
        pixels = image.load()
        for _ in range(900):
            pixels[random.randrange(image.width), random.randrange(image.height)] = 0

        first = detect_regions(image)
        second = detect_regions(image)
        self.assertEqual(first, second)
        self._assert_invariants(image, first)

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
        with patch("pdfsum.segment._content_mask", wraps=_content_mask) as content_mask:
            detect_regions(img)
        content_mask.assert_called_once_with(img)

    def test_instrumentacion_estructural(self):
        """La página grande expone instrumentación y reutiliza la máscara."""
        img = Image.new("L", (2542, 5100), 255)
        draw = ImageDraw.Draw(img)
        for y in range(200, 4700, 45):
            draw.rectangle((180, y, 1120, y + 18), fill=0)
            draw.rectangle((1420, y, 2360, y + 18), fill=0)
        timings: dict[str, float] = {}
        with patch("pdfsum.segment._content_mask", wraps=_content_mask) as content_mask:
            detect_regions(img, timings=timings)
        content_mask.assert_called_once_with(img)
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
