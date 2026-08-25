"""Tests de integración del pipeline con estrategia de porción (C9, C10)."""

import unittest

from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.contract import DocType, SourceKind
from pdfsum.pipeline import summarize_document, summarize_pdf

_MANUAL = (
    "MINISTÉRIO DA SAÚDE - Manual\n\n"
    + "APRESENTAÇÃO\nEste manual apresenta diretrizes. " * 15
    + "\n\nSUMÁRIO\n1. Introdução  2. Métodos\n\n"
    + "INTRODUÇÃO\nO contexto exige diretrizes claras. " * 20
    + "\n\n"
    + ("corpo extenso do manual " * 3000)
)


class TestPipelineFase1(unittest.TestCase):
    def test_pipeline_applies_excerpt(self):
        """C9: el pipeline aplica porción y lo registra en meta."""
        res = summarize_document(
            doc_id="m1",
            text=_MANUAL,
            summarizer=FakeSummarizer(),
            pages=30,
            doc_type=DocType.MANUAL,
            max_chars=4000,
        )
        self.assertEqual(res.meta["excerpt_strategy"], "manual")
        self.assertTrue(res.meta["excerpt_truncated"])
        self.assertLessEqual(res.meta["excerpt_chars"], 4000)
        self.assertIn("portada", res.meta["excerpt_parts"])

    def test_manual_largo(self):
        """C10: manual largo -> incluye estructura, no prefijo ciego."""
        res = summarize_document(
            doc_id="m2",
            text=_MANUAL,
            summarizer=FakeSummarizer(),
            pages=30,
            doc_type=DocType.MANUAL,
            max_chars=4000,
        )
        parts = set(res.meta["excerpt_parts"])
        # evidencia de enrutado por estructura (no solo 'portada'/prefijo)
        self.assertTrue({"apresentacao", "sumario", "introducao"} & parts)

    def test_summarize_pdf_via_transcriber(self):
        """C9 (extra): summarize_pdf usa el puerto Transcriber."""
        tr = FakeTranscriber(text=_MANUAL, pages=30, source_kind=SourceKind.NATIVO)
        res = summarize_pdf(
            "/tmp/x.pdf",
            transcriber=tr,
            summarizer=FakeSummarizer(),
            doc_type=DocType.MANUAL,
            max_chars=4000,
        )
        self.assertEqual(res.doc_id, "x")
        self.assertEqual(res.meta["pages"], 30)
        self.assertEqual(res.meta["excerpt_strategy"], "manual")


if __name__ == "__main__":
    unittest.main()
