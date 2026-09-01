"""Comparación relativa de segmentación; se activa de forma explícita."""

import os
import statistics
import time
import unittest

from PIL import Image, ImageDraw

from benchmarks.benchmark_segment import _previous_regions
from pdfsum.segment import detect_regions


@unittest.skipUnless(
    os.getenv("PDFSUM_RUN_PERFORMANCE") == "1",
    "suite de performance desactivada; usa make test-performance",
)
class TestSegmentPerformance(unittest.TestCase):
    def test_optimizacion_supera_baseline_y_conserva_regiones(self):
        """La versión optimizada es relativamente más rápida y equivalente."""
        image = Image.new("L", (1200, 1600), 255)
        draw = ImageDraw.Draw(image)
        for y in range(80, 1500, 32):
            draw.rectangle((60, y, 540, y + 12), fill=0)
            draw.rectangle((660, y, 1140, y + 12), fill=0)

        baseline_regions = _previous_regions(image)
        optimized_regions = detect_regions(image)
        self.assertEqual(len(optimized_regions), len(baseline_regions))

        baseline_times = []
        optimized_times = []
        for _ in range(3):
            started = time.perf_counter()
            _previous_regions(image)
            baseline_times.append(time.perf_counter() - started)
            started = time.perf_counter()
            detect_regions(image)
            optimized_times.append(time.perf_counter() - started)

        ratio = statistics.median(baseline_times) / statistics.median(optimized_times)
        self.assertGreaterEqual(ratio, 3.0)


if __name__ == "__main__":
    unittest.main()
