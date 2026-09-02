"""Tests para pipeline con long_strategy='hierarchical' (criterios C4-C5)."""

import unittest

from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.contract import DocType
from pdfsum.pipeline import summarize_document


class _CountingSummarizer(FakeSummarizer):
    """Spy: cuenta las llamadas al puerto Summarizer (FIX-HIERARCHICAL C1)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0
        self.doc_ids: list[str] = []

    def summarize(self, req):
        self.calls += 1
        self.doc_ids.append(req.doc_id)
        return super().summarize(req)


class TestCapituloLargoUnaSolaPasada(unittest.TestCase):
    """FIX-HIERARCHICAL-DOBLE-RESUMEN: C1 y C2."""

    def test_capitulo_largo_una_sola_pasada_de_bloques(self):
        """C1: capítulo de N bloques -> N+1 llamadas al summarizer, no 2x."""
        from pdfsum.chunking import split_blocks
        from pdfsum.pipeline import _summarize_chapter

        max_chars = 1000
        text = "Párrafo de contenido del capítulo.\n\n" * 60  # > 1 bloque
        n_blocks = len(split_blocks(text, max_chars=max_chars))
        self.assertGreater(n_blocks, 1, "el fixture debe exceder un bloque")

        spy = _CountingSummarizer()
        secciones, meta = _summarize_chapter(
            "doc#cap1", text, spy, "es", "B", max_chars=max_chars
        )

        # N bloques + 1 consolidación; el bug duplicaba: 2*(N+1).
        self.assertEqual(spy.calls, n_blocks + 1)

        # C2: contrato intacto (secciones dict no vacío, meta de bloques).
        self.assertTrue(secciones)
        self.assertIsInstance(secciones, dict)
        self.assertEqual(meta["n_bloques"], n_blocks)
        self.assertEqual(meta["excerpt_strategy"], "blocks")

    def test_capitulo_corto_una_llamada(self):
        """C2: capítulo que cabe en max_chars -> exactamente 1 llamada."""
        from pdfsum.pipeline import _summarize_chapter

        spy = _CountingSummarizer()
        secciones, meta = _summarize_chapter(
            "doc#cap1", "Texto corto.", spy, "es", "B", max_chars=1000
        )
        self.assertEqual(spy.calls, 1)
        self.assertTrue(secciones)
        self.assertEqual(meta["n_bloques"], 1)


class TestPipelineHierarchical(unittest.TestCase):
    """Tests de integración para el pipeline jerárquico."""

    def test_summarize_hierarchical_fake(self):
        """C4: pipeline con long_strategy='hierarchical' usa fake summarizer."""
        # Texto LARGO con pseudo-capítulos (>40K chars para disparar hierarquía)
        text = (
            "Prefacio: este es un libro.\n\n"
            "Capítulo\n\n1\n\n"
            "INTRODUCCIÓN\n"
            "Párrafo intro.\n"
            * 1000  # ~15K chars
            + "\n\nCapítulo\n\n2\n\n"
            "MÉTODOS\n"
            "Párrafo método.\n"
            * 1000  # ~15K chars
            + "\n\nCapítulo\n\n3\n\n"
            "RESULTADOS\n"
            "Párrafo resultado.\n" * 1000  # ~15K chars
        )

        result = summarize_document(
            doc_id="test_book",
            text=text,
            summarizer=FakeSummarizer(),
            pages=20,
            doc_type=DocType.MANUAL,
            long_strategy="hierarchical",
        )

        # Verificar metadatos
        self.assertEqual(result.meta["excerpt_strategy"], "hierarchical")
        self.assertGreater(result.meta.get("n_capitulos", 0), 0)
        self.assertFalse(result.meta["excerpt_truncated"])

        # Verificar secciones (FakeSummarizer devuelve claves en pt)
        self.assertTrue(result.secciones)
        self.assertGreater(len(result.secciones), 0)

    def test_hierarchical_cobertura_100(self):
        """C5: excerpt_chars == texto completo, truncated=false."""
        # Texto MUY largo con capítulos explícitos (>40K para disparar jerarquía)
        text = (
            "Intro\n\n"
            "Capítulo\n\n1\n\nTÍTULO1\n"
            + ("Contenido.\n" * 2000)
            + "\nCapítulo\n\n2\n\nTÍTULO2\n"
            + ("Contenido.\n" * 2000)
        )

        result = summarize_document(
            doc_id="test",
            text=text,
            summarizer=FakeSummarizer(),
            doc_type=DocType.MANUAL,
            long_strategy="hierarchical",
        )

        # Verificar que cubre ~100% y no está truncado (tolerancia de ±5 chars por strip)
        self.assertAlmostEqual(result.meta["excerpt_chars"], len(text), delta=5)
        self.assertFalse(result.meta["excerpt_truncated"])
        self.assertEqual(result.meta["excerpt_strategy"], "hierarchical")

    def test_hierarchical_fallback_sin_capitulos(self):
        """Si no hay capítulos, degrada a 'blocks' automáticamente."""
        text = "Texto largo sin capítulos. " * 3000  # ~80K chars

        result = summarize_document(
            doc_id="test",
            text=text,
            summarizer=FakeSummarizer(),
            doc_type=DocType.MANUAL,
            long_strategy="hierarchical",
            max_chars=40000,
        )

        # Sin capítulos, debe degradar a blocks
        self.assertEqual(result.meta["excerpt_strategy"], "blocks")
        self.assertFalse(result.meta["excerpt_truncated"])


if __name__ == "__main__":
    unittest.main()
