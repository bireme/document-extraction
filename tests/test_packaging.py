"""Tests de empaquetado (criterios C1, C2)."""
import unittest
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


class TestPackaging(unittest.TestCase):
    def test_pyproject(self):
        """C1: pyproject válido, paquete src, entry point pdfsum."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(data["project"]["name"], "pdfsum")
        self.assertIn("pdfsum", data["project"]["scripts"])
        self.assertEqual(data["project"]["scripts"]["pdfsum"], "pdfsum.cli:main")
        self.assertEqual(data["tool"]["setuptools"]["package-dir"][""], "src")
        self.assertGreaterEqual(
            data["project"]["requires-python"].replace(">=", ""), "3.10")

    def test_version_sync(self):
        """C2: versión de pyproject == pdfsum.__version__."""
        import pdfsum
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(data["project"]["version"], pdfsum.__version__)


if __name__ == "__main__":
    unittest.main()
