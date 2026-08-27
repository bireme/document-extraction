"""Tests de empaquetado (criterios C1, C2)."""

import unittest
from pathlib import Path

try:
    import tomllib  # stdlib desde Python 3.11
except ModuleNotFoundError:  # Python 3.10 (requires-python = ">=3.10")
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


class TestPackaging(unittest.TestCase):
    def test_pyproject(self):
        """C1: pyproject válido, paquete src, entry point pdfsum."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(data["project"]["name"], "pdfsum")
        self.assertIn("pdfsum", data["project"]["scripts"])
        self.assertEqual(data["project"]["scripts"]["pdfsum"], "pdfsum.cli:main")
        # Fase 12: backend moderno hatchling (antes: setuptools).
        self.assertIn("hatchling", data["build-system"]["requires"][0])
        self.assertEqual(data["build-system"]["build-backend"], "hatchling.build")
        self.assertEqual(
            data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"],
            ["src/pdfsum"],
        )
        self.assertGreaterEqual(
            data["project"]["requires-python"].replace(">=", ""), "3.10"
        )

    def test_version_sync(self):
        """C2: versión de pyproject == pdfsum.__version__."""
        import pdfsum

        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(data["project"]["version"], pdfsum.__version__)


if __name__ == "__main__":
    unittest.main()
