"""Tests del routing de OCR por confianza (criterios C1, C2)."""
import unittest

from pdfsum.ocr_routing import parse_tsv_confidence, route_page

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
        self.assertEqual(route_page(75.0, 15), "tesseract")   # justo en umbral
        self.assertEqual(route_page(50.0, 100), "vlm")         # conf baja
        self.assertEqual(route_page(90.0, 5), "vlm")           # pocas palabras
        self.assertEqual(route_page(0.0, 0), "vlm")            # nada legible

    def test_parse_tsv(self):
        """C2: confianza media y nº de palabras desde TSV (ignora vacías)."""
        conf, words = parse_tsv_confidence(_TSV)
        self.assertEqual(words, 3)                    # 3 tokens con texto y conf>=0
        self.assertAlmostEqual(conf, (94.5 + 91.0 + 96.0) / 3, places=2)
        # TSV vacío -> (0,0)
        self.assertEqual(parse_tsv_confidence(""), (0.0, 0))


if __name__ == "__main__":
    unittest.main()
