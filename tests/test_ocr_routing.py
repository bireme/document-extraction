"""Tests del routing de OCR por confianza (criterios C1, C2)."""

import unittest

from pdfsum.ocr_routing import parse_tsv_confidence, parse_tsv_lines, route_page

_TSV = (
    "level\tpage_num\tconf\ttext\n"
    "5\t1\t94.5\thola\n"
    "5\t1\t91.0\tmundo\n"
    "5\t1\t-1\t\n"
    "5\t1\t96.0\ttexto\n"
)


class TestOcrRouting(unittest.TestCase):
    def test_route_page(self):
        """C1: alta confianza -> tesseract; baja -> vlm."""
        self.assertEqual(route_page(94.0, 100), "tesseract")
        self.assertEqual(route_page(75.0, 15), "tesseract")  # justo en umbral
        self.assertEqual(route_page(50.0, 100), "vlm")  # conf baja
        self.assertEqual(route_page(90.0, 5), "vlm")  # pocas palabras
        self.assertEqual(route_page(0.0, 0), "vlm")  # nada legible

    def test_parse_tsv(self):
        """C2: confianza media y nº de palabras desde TSV (ignora vacías)."""
        conf, words = parse_tsv_confidence(_TSV)
        self.assertEqual(words, 3)  # 3 tokens con texto y conf>=0
        self.assertAlmostEqual(conf, (94.5 + 91.0 + 96.0) / 3, places=2)
        # TSV vacío -> (0,0)
        self.assertEqual(parse_tsv_confidence(""), (0.0, 0))


class TestTsvLines(unittest.TestCase):
    def test_idiomas_y_espacios(self):
        for text in (
            "Olá, ação e saúde pública!",
            "¡Atención! Información y población: ¿sí?",
            'Health research: "quoted" words & 50%.',
        ):
            with self.subTest(text=text):
                tsv = "conf\ttext\n" + "\n".join(
                    f"95\t  {word}  " for word in text.split()
                )
                self.assertEqual(parse_tsv_lines(tsv), text)

    def test_comillas_literales(self):
        self.assertEqual(
            parse_tsv_lines('conf\ttext\n95\t"hola\n95\tmundo"'),
            '"hola mundo"',
        )

    def test_lineas_bloques_parrafos_paginas(self):
        tsv = "page_num\tblock_num\tpar_num\tline_num\tconf\ttext\n"
        tsv += "1\t2\t1\t1\t95\tfinal\n"
        tsv += "1\t1\t1\t1\t95\tprimera\n"
        tsv += "1\t1\t1\t1\t95\tlínea\n"
        tsv += "1\t1\t1\t2\t95\tsegunda\n"
        tsv += "1\t1\t2\t1\t95\tpárrafo\n"
        tsv += "2\t1\t1\t1\t95\tpágina\n"
        self.assertEqual(
            parse_tsv_lines(tsv), "primera línea\nsegunda\npárrafo\nfinal\npágina"
        )

    def test_vacio_y_confianza_invalida(self):
        for tsv in ("", "conf\ttext\n", "conf\ttext\n-1\tignorar\nx\tignorar\n95\t  "):
            with self.subTest(tsv=tsv):
                self.assertEqual(parse_tsv_lines(tsv), "")
        self.assertEqual(
            parse_tsv_lines("conf\ttext\n-1\tno\ninvalida\tno\n0\tsí"), "sí"
        )


if __name__ == "__main__":
    unittest.main()
