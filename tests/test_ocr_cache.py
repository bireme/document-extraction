"""FASE16 C4: caché de transcripción versionada por hash + pipeline."""

import json
import tempfile
import unittest
from pathlib import Path

from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.ocr_meta import meta_path, read_meta
from pdfsum.adapters.pdf_batch import transcribe_pdfs
from pdfsum.workspace import Workspace

_TEXTO = "La salud pública es una disciplina de la población. " * 30


class _CountingTranscriber(FakeTranscriber):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0

    def transcribe(self, path):
        self.calls += 1
        return super().transcribe(path)


class TestCacheVersionada(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        base = Path(self._td.name)
        self.in_dir = base / "in"
        self.in_dir.mkdir()
        self.pdf = self.in_dir / "doc1.pdf"
        self.pdf.write_bytes(b"%PDF-fake-1")
        self.ws = Workspace(str(base / "ws"))
        self.tx = _CountingTranscriber(_TEXTO, pages=1)

    def tearDown(self):
        self._td.cleanup()

    def _run(self, **kwargs):
        return transcribe_pdfs(str(self.in_dir), self.ws, self.tx, **kwargs)

    def test_cache_valida_se_reutiliza(self):
        self._run()
        self.assertEqual(self.tx.calls, 1)
        meta = self._run()
        self.assertEqual(self.tx.calls, 1)  # sin re-OCR
        self.assertTrue(meta["doc1"]["cached"])

    def test_pdf_cambiado_retranscribe(self):
        self._run()
        self.pdf.write_bytes(b"%PDF-fake-2-DISTINTO")
        meta = self._run()
        self.assertEqual(self.tx.calls, 2)
        self.assertFalse(meta["doc1"]["cached"])
        persisted = read_meta(self.ws.ocr_path("doc1"))
        self.assertNotIn("legacy", persisted)

    def test_pipeline_version_distinta_retranscribe(self):
        self._run()
        ocr_file = self.ws.ocr_path("doc1")
        persisted = read_meta(ocr_file)
        persisted["ocr_pipeline_version"] = "0-antigua"
        meta_path(ocr_file).write_text(json.dumps(persisted), encoding="utf-8")
        self._run()
        self.assertEqual(self.tx.calls, 2)

    def test_cache_legacy_se_reutiliza_con_marca(self):
        """txt sin meta (corpus pre-FASE16): NUNCA re-OCR silencioso."""
        ocr_file = self.ws.ocr_path("doc1")
        ocr_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_text = "=== pág 1 ===\nuno\n=== pág 2 ===\ndos\n=== pág 3 ===\ntres"
        ocr_file.write_text(legacy_text, encoding="utf-8")

        meta = self._run()
        self.assertEqual(self.tx.calls, 0)  # reutilizada, sin re-OCR
        self.assertTrue(meta["doc1"]["cached"])
        # pages sale de la meta legacy (fin del hack ad-hoc en pdf_batch)
        self.assertEqual(meta["doc1"]["pages"], 3)
        persisted = read_meta(ocr_file)
        self.assertTrue(persisted["legacy"])

        # segunda pasada: sigue reutilizando la legacy (mismo PDF)
        self._run()
        self.assertEqual(self.tx.calls, 0)

    def test_legacy_con_pdf_cambiado_retranscribe(self):
        ocr_file = self.ws.ocr_path("doc1")
        ocr_file.parent.mkdir(parents=True, exist_ok=True)
        ocr_file.write_text("viejo", encoding="utf-8")
        self._run()  # genera meta legacy con hash actual
        self.assertEqual(self.tx.calls, 0)
        self.pdf.write_bytes(b"%PDF-fake-NUEVO")
        self._run()
        self.assertEqual(self.tx.calls, 1)

    def test_retranscribe_fuerza_reocr(self):
        self._run()
        self._run(retranscribe=True)
        self.assertEqual(self.tx.calls, 2)


if __name__ == "__main__":
    unittest.main()
