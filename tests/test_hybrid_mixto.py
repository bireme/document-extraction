"""FASE17 C2: decisión nativo/OCR por página en HybridOcrTranscriber."""

import unittest
from unittest.mock import patch

from pdfsum.classify import aggregate_source, route_pages
from pdfsum.contract import SourceKind

# Página "rica" en texto nativo (> 100 chars sin espacios).
_RICA = ("Texto nativo abundante de la página con contenido real. " * 5).strip()
_POBRE = ""  # página escaneada: pdftotext no devuelve nada


class TestRoutingDominio(unittest.TestCase):
    def test_route_pages(self):
        chars = [500, 0, 30, 200]
        self.assertEqual(route_pages(chars), ["nativo", "ocr", "ocr", "nativo"])

    def test_aggregate_source(self):
        self.assertEqual(aggregate_source(["nativo", "nativo"]), SourceKind.NATIVO)
        self.assertEqual(aggregate_source(["ocr", "ocr"]), SourceKind.ESCANEADO)
        self.assertEqual(aggregate_source(["nativo", "ocr"]), SourceKind.MIXTO)
        self.assertEqual(aggregate_source([]), SourceKind.ESCANEADO)


def _make_transcriber():
    from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber

    with patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/bin/x"):
        return HybridOcrTranscriber(lang="spa")


def _fake_run_factory(native_pages: list[str], pages: int):
    """Simula pdfinfo y pdftotext (con \\f entre páginas)."""

    def fake_run(cmd, timeout=120):
        if cmd[0] == "pdfinfo":
            return f"Pages: {pages}\n"
        if cmd[0] == "pdftotext":
            return "\f".join(native_pages) + "\f"
        raise AssertionError(f"subproceso inesperado en test: {cmd}")

    return fake_run


class TestTranscribeMixto(unittest.TestCase):
    def _transcribe(self, native_pages, ocr_spy_text="TEXTO OCR"):
        tx = _make_transcriber()
        ocr_calls: list[int] = []

        def fake_single_page(path, p, total, td):
            ocr_calls.append(p)
            return ocr_spy_text, {
                "page": p,
                "source": "tesseract",
                "conf": 80.0,
                "words": 10,
                "chars": len(ocr_spy_text),
            }

        tx._ocr_single_page = fake_single_page
        with (
            patch(
                "pdfsum.adapters.hybrid_ocr._run",
                side_effect=_fake_run_factory(native_pages, len(native_pages)),
            ),
            patch(
                "pdfsum.adapters.hybrid_ocr.shutil.which",
                return_value="/bin/x",
            ),
        ):
            result = tx.transcribe("/fake/doc.pdf")
        return result, ocr_calls

    def test_mixto_solo_ocr_de_paginas_pobres(self):
        """C2: N=4 páginas, K=2 pobres -> solo K pasan por OCR."""
        result, ocr_calls = self._transcribe([_RICA, _POBRE, _RICA, _POBRE])
        self.assertEqual(ocr_calls, [2, 4])  # solo las pobres
        self.assertEqual(result.source_kind, SourceKind.MIXTO)
        # texto de las 4 páginas presente
        self.assertEqual(result.text.count("=== pág"), 4)
        self.assertIn("Texto nativo abundante", result.text)
        self.assertIn("TEXTO OCR", result.text)
        # pages_detail con fuentes correctas
        fuentes = [d["source"] for d in result.pages_detail]
        self.assertEqual(fuentes, ["nativo", "tesseract", "nativo", "tesseract"])

    def test_todas_nativas_formato_actual(self):
        """Caso borde: NATIVO puro conserva el formato sin marcadores."""
        result, ocr_calls = self._transcribe([_RICA, _RICA])
        self.assertEqual(ocr_calls, [])
        self.assertEqual(result.source_kind, SourceKind.NATIVO)
        self.assertNotIn("=== pág", result.text)
        self.assertEqual(len(result.pages_detail), 2)
        self.assertTrue(all(d["source"] == "nativo" for d in result.pages_detail))

    def test_ninguna_nativa_escaneado(self):
        """Caso borde: ESCANEADO puro pasa por el camino OCR existente."""
        result, ocr_calls = self._transcribe([_POBRE, _POBRE])
        self.assertEqual(result.source_kind, SourceKind.ESCANEADO)
        self.assertEqual(ocr_calls, [1, 2])
        self.assertEqual(result.text.count("=== pág"), 2)


if __name__ == "__main__":
    unittest.main()
