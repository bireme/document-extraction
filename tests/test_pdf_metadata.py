"""Tests del adaptador pdf_metadata.py (criterio C2, FASE15).

Sin pdfinfo real: subprocess mockeado.
"""

import subprocess
import unittest
from unittest.mock import patch

from pdfsum.adapters.pdf_metadata import read_pdf_info

_PDFINFO_OUT = """Title:           Urología
Subject:         Capítulo 10. Laparascopia en Urología
Keywords:
Author:          René Salas Cabrera
Creator:
Producer:        Solid Converter PDF
CreationDate:    Wed May  2 10:44:32 2012 EDT
Pages:           14
Page size:       612 x 790 pts
"""


def _proc(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["pdfinfo"], returncode=returncode, stdout=stdout, stderr=""
    )


class TestReadPdfInfo(unittest.TestCase):
    def test_parsea_campos_normalizados(self):
        with patch("subprocess.run", return_value=_proc(_PDFINFO_OUT)):
            meta = read_pdf_info("x.pdf")
        self.assertEqual(meta["title"], "Urología")
        self.assertEqual(meta["subject"], "Capítulo 10. Laparascopia en Urología")
        self.assertEqual(meta["author"], "René Salas Cabrera")
        self.assertEqual(meta["pages"], 14)
        self.assertIn("2012", meta["creation_date"])

    def test_campos_vacios_no_se_incluyen(self):
        with patch("subprocess.run", return_value=_proc(_PDFINFO_OUT)):
            meta = read_pdf_info("x.pdf")
        self.assertNotIn("keywords", meta)  # Keywords: vacío en la salida

    def test_binario_ausente_devuelve_vacio(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(read_pdf_info("x.pdf"), {})

    def test_pdf_corrupto_devuelve_vacio(self):
        with patch("subprocess.run", return_value=_proc("", returncode=1)):
            self.assertEqual(read_pdf_info("bad.pdf"), {})

    def test_timeout_devuelve_vacio(self):
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pdfinfo", timeout=15),
        ):
            self.assertEqual(read_pdf_info("x.pdf"), {})

    def test_pages_no_numerico_se_omite(self):
        with patch("subprocess.run", return_value=_proc("Pages: muchas\n")):
            self.assertEqual(read_pdf_info("x.pdf"), {})


if __name__ == "__main__":
    unittest.main()
