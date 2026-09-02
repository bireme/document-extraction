"""FASE16 C3: meta.json de transcripción (hash, quality, roundtrip)."""

import tempfile
import unittest
from pathlib import Path

from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.ocr_meta import (
    OCR_PIPELINE_VERSION,
    build_legacy_meta,
    build_meta,
    cache_valid,
    infer_pages_from_text,
    meta_path,
    read_meta,
    sha256_file,
    write_meta,
)
from pdfsum.adapters.pdf_batch import transcribe_pdfs
from pdfsum.contract import SourceKind, TranscriptResult
from pdfsum.workspace import Workspace

_TEXTO = "La salud pública es una disciplina de la población. " * 30


def _fake_pdf(dir_: Path, name: str = "doc1.pdf", data: bytes = b"%PDF-fake-1") -> Path:
    p = dir_ / name
    p.write_bytes(data)
    return p


class TestBuildMeta(unittest.TestCase):
    def test_meta_completa_con_quality_agregada(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = _fake_pdf(Path(td))
            tr = TranscriptResult(
                text=_TEXTO,
                pages=3,
                source_kind=SourceKind.ESCANEADO,
                pages_detail=[
                    {
                        "page": 1,
                        "source": "tesseract",
                        "conf": 90.0,
                        "words": 100,
                        "chars": 500,
                    },
                    {
                        "page": 2,
                        "source": "vlm",
                        "conf": 40.0,
                        "words": 50,
                        "chars": 300,
                    },
                    {"page": 3, "source": "sin_imagen", "chars": 0},
                ],
            )
            meta = build_meta("doc1", pdf, tr, "por+eng+spa")
            self.assertEqual(meta["ocr_pipeline_version"], OCR_PIPELINE_VERSION)
            self.assertEqual(meta["pdf_sha256"], sha256_file(pdf))
            self.assertEqual(meta["pages"], 3)
            self.assertEqual(meta["lang_ocr"], "por+eng+spa")
            self.assertEqual(len(meta["pages_detail"]), 3)
            q = meta["quality"]
            # conf media ponderada por palabras: (90*100 + 40*50) / 150
            self.assertAlmostEqual(q["conf_media"], 73.33, places=2)
            self.assertEqual(q["paginas_vlm"], 1)
            self.assertEqual(q["paginas_vacias"], 1)

    def test_quality_sin_detalle_ocr(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = _fake_pdf(Path(td))
            tr = TranscriptResult(
                text=_TEXTO,
                pages=2,
                source_kind=SourceKind.NATIVO,
                pages_detail=[
                    {"page": 1, "source": "nativo"},
                    {"page": 2, "source": "nativo"},
                ],
            )
            q = build_meta("doc1", pdf, tr, "por")["quality"]
            self.assertNotIn("conf_media", q)
            self.assertEqual(q["paginas_vlm"], 0)


class TestRoundtripYValidez(unittest.TestCase):
    def test_write_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            ocr_file = Path(td) / "doc1.txt"
            write_meta(ocr_file, {"meta_version": "1.0", "pages": 5})
            self.assertTrue(meta_path(ocr_file).exists())
            self.assertEqual(read_meta(ocr_file)["pages"], 5)

    def test_read_meta_ausente_o_corrupta(self):
        with tempfile.TemporaryDirectory() as td:
            ocr_file = Path(td) / "doc1.txt"
            self.assertIsNone(read_meta(ocr_file))
            meta_path(ocr_file).write_text("{corrupto", encoding="utf-8")
            self.assertIsNone(read_meta(ocr_file))

    def test_cache_valid(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = _fake_pdf(Path(td))
            ok = {
                "ocr_pipeline_version": OCR_PIPELINE_VERSION,
                "pdf_sha256": sha256_file(pdf),
            }
            self.assertTrue(cache_valid(ok, pdf))
            self.assertFalse(cache_valid(None, pdf))
            self.assertFalse(cache_valid({**ok, "legacy": True}, pdf))
            self.assertFalse(cache_valid({**ok, "pdf_sha256": "otro"}, pdf))
            self.assertFalse(cache_valid({**ok, "ocr_pipeline_version": "0"}, pdf))

    def test_infer_pages_y_legacy_meta(self):
        texto = "=== pág 1 ===\nuno\n=== pág 2 ===\ndos"
        self.assertEqual(infer_pages_from_text(texto), 2)
        self.assertEqual(infer_pages_from_text("sin marcadores"), 1)
        with tempfile.TemporaryDirectory() as td:
            pdf = _fake_pdf(Path(td))
            meta = build_legacy_meta("doc1", pdf, texto)
            self.assertTrue(meta["legacy"])
            self.assertEqual(meta["pages"], 2)
            self.assertEqual(meta["pdf_sha256"], sha256_file(pdf))


class TestTranscribeEscribeMeta(unittest.TestCase):
    def test_transcribe_pdfs_escribe_txt_y_meta(self):
        with tempfile.TemporaryDirectory() as td:
            in_dir = Path(td) / "in"
            in_dir.mkdir()
            _fake_pdf(in_dir)
            ws = Workspace(str(Path(td) / "ws"))
            detail = [{"page": 1, "source": "nativo"}]
            meta = transcribe_pdfs(
                str(in_dir),
                ws,
                FakeTranscriber(_TEXTO, pages=1, pages_detail=detail),
            )
            self.assertFalse(meta["doc1"]["cached"])
            persisted = read_meta(ws.ocr_path("doc1"))
            self.assertEqual(persisted["pages_detail"], detail)
            self.assertEqual(persisted["ocr_pipeline_version"], OCR_PIPELINE_VERSION)


if __name__ == "__main__":
    unittest.main()
