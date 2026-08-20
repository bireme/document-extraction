"""Tests de los subcomandos doctor y verify (criterios C8, C9)."""
import io
import unittest
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory

from pdfsum.cli import main


class TestCLIRepro(unittest.TestCase):
    def test_cli_doctor(self):
        """C8: 'doctor' imprime reporte y devuelve código según entorno."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["doctor"])
        out = buf.getvalue()
        self.assertIn("Verificación de entorno", out)
        self.assertIn("pdftotext", out)
        self.assertIn(rc, (0, 1))  # 0 si entorno mínimo ok, 1 si falta duro

    def test_cli_verify(self):
        """C9: 'verify --fake' corre el arnés sobre la muestra incluida."""
        with TemporaryDirectory() as td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["verify", "--fake", "--workspace", td,
                           "--min-coverage", "0.0"])
            out = buf.getvalue()
            self.assertIn("Aceptación:", out)
            # con --fake y umbral 0 el arnés corre y emite veredicto
            self.assertIn(rc, (0, 1))


if __name__ == "__main__":
    unittest.main()
