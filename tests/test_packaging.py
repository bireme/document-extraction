"""Tests de empaquetado, contenido del wheel e instalación limpia."""

import os
import subprocess
import sys
import unittest
import venv
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

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

    def test_wheel_contiene_runtime_y_excluye_artefactos_de_desarrollo(self):
        """El wheel incluye cada módulo runtime y excluye tests y benchmarks."""
        with TemporaryDirectory() as td:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--wheel",
                    "--no-isolation",
                    "--outdir",
                    td,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
            wheel = next(Path(td).glob("*.whl"))
            with ZipFile(wheel) as archive:
                names = set(archive.namelist())
                metadata_name = next(
                    name for name in names if name.endswith(".dist-info/METADATA")
                )
                metadata = archive.read(metadata_name).decode("utf-8")
            runtime_modules = {
                f"pdfsum/{path.name}" for path in (ROOT / "src" / "pdfsum").glob("*.py")
            }
            self.assertLessEqual(runtime_modules, names)
            self.assertFalse(any(name.startswith("tests/") for name in names))
            self.assertFalse(any(name.startswith("benchmarks/") for name in names))
            self.assertIn("Requires-Dist: pillow>=10", metadata)

    @unittest.skipUnless(
        os.getenv("PDFSUM_RUN_PACKAGING") == "1",
        "instalación limpia desactivada; define PDFSUM_RUN_PACKAGING=1",
    )
    def test_wheel_instalado_en_venv_limpio_importa_y_muestra_help(self):
        """La instalación con dependencias expone pdfsum, Pillow y la CLI."""
        with TemporaryDirectory() as td:
            root = Path(td)
            dist = root / "dist"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--wheel",
                    "--no-isolation",
                    "--outdir",
                    str(dist),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
            environment = root / "venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / "bin" / "python"
            pip = environment / "bin" / "pip"
            command = environment / "bin" / "pdfsum"
            wheel = next(dist.glob("*.whl"))
            subprocess.run(
                [str(pip), "install", str(wheel)],
                capture_output=True,
                text=True,
                check=True,
                timeout=180,
            )
            imported = subprocess.run(
                [str(python), "-c", "import pdfsum, PIL"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            help_result = subprocess.run(
                [str(command), "--help"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("pdfsum", help_result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
