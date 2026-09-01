"""E2E real: poppler, Tesseract, segmentación, pipeline, QA y reportes."""

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber
from pdfsum.adapters.pdf_batch import run_batch_pdfs
from pdfsum.contract import SummarizeRequest
from pdfsum.segment import detect_regions, sort_reading_order
from pdfsum.templates import section_keys
from pdfsum.workspace import Workspace
from tests.fixtures.pdf_factory import (
    build_scanned_image,
    write_corrupt_pdf,
    write_native_pdf,
    write_scanned_pdf,
)


class _DeterministicSummarizer:
    """Reemplaza solamente el LLM y conserva una salida lingüística estable."""

    _TEXT: ClassVar[dict[str, str]] = {
        "en": "the health study and the results provide evidence for public health",
        "es": "el estudio de salud y los resultados aportan evidencia para la salud",
        "pt": "o estudo de saúde e os resultados apresentam evidência para a saúde",
    }

    def summarize(self, request: SummarizeRequest) -> dict[str, str]:
        text = self._TEXT.get(request.lang, self._TEXT["pt"])
        return {name: f"{text}: {name}" for name in section_keys(request.template)}


class _DeterministicPageOCR:
    """Fallback reproducible que deja visible la región procesada."""

    def ocr_image(self, image_path: str, lang: str) -> str:
        return f"región {Path(image_path).stem} idioma {lang} salud resultados"


class TestPdfFlowE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [
            tool
            for tool in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract")
            if not shutil.which(tool)
        ]
        if missing:
            raise unittest.SkipTest(
                f"dependencias opcionales ausentes para E2E: {', '.join(missing)}"
            )

    def _assert_report(self, workspace: Workspace, expected: int) -> dict:
        report = json.loads(workspace.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["report_version"], "3.0")
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["progress"]["discovered"], expected)
        self.assertEqual(report["progress"]["processed"], expected)
        self.assertEqual(report["progress"]["completed"], expected)
        self.assertEqual(report["progress"]["failed"], 0)
        for field in (
            "run_id",
            "started_at",
            "updated_at",
            "metrics",
            "infrastructure",
            "documents",
        ):
            self.assertIn(field, report)
        return report

    def test_pdf_nativo_recorrer_flujo_completo(self):
        """Un PDF con texto embebido llega hasta summary, QA y report.json."""
        with TemporaryDirectory() as td:
            root = Path(td)
            input_dir = root / "entrada"
            input_dir.mkdir()
            line = "the health study methods results and conclusions are reproducible"
            write_native_pdf(input_dir / "nativo.pdf", [line] * 8)
            workspace = Workspace(root / "salida", logs_dir=root / "logs")

            returned = run_batch_pdfs(
                str(input_dir),
                workspace,
                HybridOcrTranscriber(lang="eng", vlm=_DeterministicPageOCR()),
                _DeterministicSummarizer(),
            )

            report = self._assert_report(workspace, 1)
            self.assertEqual(returned["status"], report["status"])
            document = report["documents"][0]
            self.assertEqual(document["source_kind"], "nativo")
            self.assertEqual(document["status"], "completed")
            self.assertTrue(document["qa_ok"])
            summary = json.loads(
                workspace.summary_path("nativo").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["doc_id"], "nativo")
            self.assertEqual(summary["meta"]["pages"], 1)
            self.assertEqual(summary["meta"]["source_kind"], "nativo")
            self.assertTrue(summary["secciones"])
            self.assertTrue(summary["_qa"]["passed"])
            events = (root / "logs" / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event":"run_started"', events)
            self.assertIn('"event":"phase_completed"', events)
            self.assertIn('"event":"document_completed"', events)
            self.assertIn('"event":"run_completed"', events)

    def test_corpus_escaneado_vacio_y_corrupto_se_recupera(self):
        """Fixtures representativas recorren OCR real con LLM determinista."""
        kinds = (
            "escaneado",
            "multicolumna",
            "tabla",
            "grafico",
            "ocr_malo",
            "multilingue",
            "largo",
        )
        with TemporaryDirectory() as td:
            root = Path(td)
            input_dir = root / "entrada"
            input_dir.mkdir()
            for kind in kinds:
                write_scanned_pdf(input_dir / f"{kind}.pdf", kind)
            write_native_pdf(input_dir / "casi_vacio.pdf", [])
            write_corrupt_pdf(input_dir / "corrupto.pdf")
            workspace = Workspace(root / "salida", logs_dir=root / "logs")

            run_batch_pdfs(
                str(input_dir),
                workspace,
                HybridOcrTranscriber(
                    lang="por+eng+spa", vlm=_DeterministicPageOCR(), dpi=120
                ),
                _DeterministicSummarizer(),
            )

            report = self._assert_report(workspace, len(kinds) + 2)
            documents = {item["doc_id"]: item for item in report["documents"]}
            self.assertEqual(set(documents), set(kinds) | {"casi_vacio", "corrupto"})
            for doc_id, document in documents.items():
                with self.subTest(doc_id=doc_id):
                    self.assertEqual(document["status"], "completed")
                    self.assertEqual(document["source_kind"], "escaneado")
                    self.assertTrue(document["qa_ok"])
                    summary = json.loads(
                        workspace.summary_path(doc_id).read_text(encoding="utf-8")
                    )
                    self.assertEqual(summary["doc_id"], doc_id)
                    self.assertIn("pages", summary["meta"])
                    self.assertIn("source_kind", summary["meta"])
                    self.assertTrue(summary["secciones"])

            for doc_id in kinds:
                text = workspace.ocr_path(doc_id).read_text(encoding="utf-8")
                self.assertGreater(len(text.strip()), 20)

    def test_invariantes_visuales_del_corpus_de_regresion(self):
        """Cada fixture visual produce regiones válidas y deterministas."""
        kinds = (
            "escaneado",
            "multicolumna",
            "tabla",
            "grafico",
            "ocr_malo",
            "multilingue",
            "largo",
        )
        for kind in kinds:
            with self.subTest(kind=kind):
                image = build_scanned_image(kind)
                first = sort_reading_order(detect_regions(image))
                second = sort_reading_order(detect_regions(image))
                self.assertEqual(first, second)
                self.assertTrue(first)
                coordinates = {
                    (region.left, region.top, region.right, region.bottom)
                    for region in first
                }
                self.assertEqual(len(coordinates), len(first))
                for region in first:
                    self.assertLessEqual(0, region.left)
                    self.assertLess(region.left, region.right)
                    self.assertLessEqual(region.right, image.width)
                    self.assertLessEqual(0, region.top)
                    self.assertLess(region.top, region.bottom)
                    self.assertLessEqual(region.bottom, image.height)
                image.close()


if __name__ == "__main__":
    unittest.main()
