"""Comprueba la referencia y los contadores sin herramientas externas."""

import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.benchmark_ocr_workers import LegacyTextTranscriber, measure
from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber


class TestBenchmarkTsv(unittest.TestCase):
    def test_referencia_y_reutilizacion(self):
        for cls, expected in ((LegacyTextTranscriber, 2), (HybridOcrTranscriber, 1)):
            with self.subTest(cls=cls.__name__):
                with patch(
                    "pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/x"
                ):
                    tx = cls()
                tsv = "conf\ttext\n" + "95\tpalabra\n" * 20

                def run(cmd, timeout=120, tsv=tsv):
                    return tsv if cmd[-1] == "tsv" else "palabra " * 20

                def transcribe(path, tx=tx):
                    tx._emit_event("ocr_pagina_completada", regiones=1)
                    return tx._ocr_page(Path("region.png"))[0]

                with (
                    patch("pdfsum.adapters.hybrid_ocr._run", side_effect=run),
                    patch.object(tx, "transcribe", side_effect=transcribe),
                ):
                    text, elapsed, counts = measure(tx, Path("doc.pdf"))
                self.assertEqual(text.split(), ["palabra"] * 20)
                self.assertEqual(counts["llamadas_tesseract"], expected)
                self.assertEqual(counts["llamadas_tsv"], 1)
                self.assertEqual(counts["regiones"], 1)
                self.assertGreaterEqual(elapsed, 0)
