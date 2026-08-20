"""Tests de resumen por bloques (criterios C1-C4, C9)."""
import unittest

from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.chunking import split_blocks, summarize_in_blocks
from pdfsum.contract import DocType
from pdfsum.pipeline import summarize_document

_LONG = ("Parágrafo de conteúdo do manual. " * 30 + "\n\n") * 60  # ~grande


class TestChunking(unittest.TestCase):
    def test_split_cobertura(self):
        """C1: divide en bloques y cubre TODO el texto (sin pérdida)."""
        blocks = split_blocks(_LONG, max_chars=4000)
        self.assertGreater(len(blocks), 1)
        # cobertura: la suma de longitudes no es menor que el texto sin espacios
        joined = "".join(b.replace(" ", "").replace("\n", "") for b in blocks)
        original = _LONG.replace(" ", "").replace("\n", "")
        self.assertEqual(joined, original)

    def test_split_tam(self):
        """C2: ningún bloque excede el máximo."""
        blocks = split_blocks(_LONG, max_chars=4000)
        for b in blocks:
            self.assertLessEqual(len(b), 4000)

    def test_consolidacion(self):
        """C3: resume por bloque y consolida; meta registra n_bloques."""
        secciones, meta = summarize_in_blocks(
            "d", _LONG, FakeSummarizer(), lang="pt", template="C",
            max_chars=4000,
        )
        self.assertEqual(meta["excerpt_strategy"], "blocks")
        self.assertGreater(meta["n_bloques"], 1)
        self.assertTrue(secciones)  # produce secciones consolidadas

    def test_cobertura_total(self):
        """C4: por bloques -> no truncado, cubre todo el texto."""
        _, meta = summarize_in_blocks(
            "d", _LONG, FakeSummarizer(), lang="pt", template="C",
            max_chars=4000,
        )
        self.assertFalse(meta["excerpt_truncated"])
        self.assertEqual(meta["excerpt_chars"], len(_LONG))

    def test_pipeline_blocks(self):
        """C9: pipeline con long_strategy='blocks' cubre todo el texto."""
        res = summarize_document(
            doc_id="m", text=_LONG, summarizer=FakeSummarizer(),
            pages=30, doc_type=DocType.MANUAL, max_chars=4000,
            long_strategy="blocks",
        )
        self.assertEqual(res.meta["excerpt_strategy"], "blocks")
        self.assertFalse(res.meta["excerpt_truncated"])
        self.assertEqual(res.meta["excerpt_chars"], len(_LONG))


if __name__ == "__main__":
    unittest.main()
