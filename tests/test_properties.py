"""Propiedades de funciones puras donde ejemplos aislados dejan huecos."""

import re
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from pdfsum.chunking import split_blocks
from pdfsum.ocr_routing import route_page
from pdfsum.qa import QAReport
from pdfsum.segment import Region, valid_regions


class TestPureProperties(unittest.TestCase):
    @settings(max_examples=80, deadline=None)
    @given(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P"),
                whitelist_characters=" \n\t",
            ),
            max_size=300,
        ),
        st.integers(min_value=1, max_value=60),
    )
    def test_chunking_no_pierde_ni_duplica_contenido(self, text, max_chars):
        """Los bloques conservan la secuencia de caracteres no blancos."""
        blocks = split_blocks(text, max_chars=max_chars)
        normalized_source = re.sub(r"\s+", "", text)
        normalized_blocks = re.sub(r"\s+", "", "".join(blocks))
        self.assertEqual(normalized_blocks, normalized_source)
        self.assertTrue(all(len(block) <= max_chars for block in blocks))

    @settings(max_examples=80, deadline=None)
    @given(
        st.lists(
            st.builds(
                Region,
                st.integers(-20, 120),
                st.integers(-20, 120),
                st.integers(-20, 120),
                st.integers(-20, 120),
            ),
            max_size=40,
        )
    )
    def test_regiones_filtradas_siempre_respetan_invariantes(self, regions):
        """Ninguna región válida sale de límites, se duplica o tiene área cero."""
        valid = valid_regions(regions, 100, 100)
        coordinates = [
            (region.left, region.top, region.right, region.bottom) for region in valid
        ]
        self.assertEqual(len(coordinates), len(set(coordinates)))
        for region in valid:
            self.assertLessEqual(0, region.left)
            self.assertLess(region.left, region.right)
            self.assertLessEqual(region.right, 100)
            self.assertLessEqual(0, region.top)
            self.assertLess(region.top, region.bottom)
            self.assertLessEqual(region.bottom, 100)
            self.assertGreater(region.area(), 0)

    @settings(max_examples=80, deadline=None)
    @given(
        st.floats(allow_nan=False, allow_infinity=False),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.integers(),
    )
    def test_routing_solo_devuelve_opciones_permitidas(
        self, confidence, words, min_confidence, min_words
    ):
        """El routing es total y solo selecciona Tesseract o VLM."""
        self.assertIn(
            route_page(confidence, words, min_confidence, min_words),
            {"tesseract", "vlm"},
        )

    @settings(max_examples=80, deadline=None)
    @given(
        st.text(max_size=30),
        st.lists(
            st.tuples(st.text(max_size=20), st.text(max_size=40), st.text(max_size=10)),
            max_size=10,
        ),
    )
    def test_qareport_to_dict_representa_el_mismo_estado(self, doc_id, failures):
        """Serializar varias veces no muta ni contradice el estado del QA."""
        report = QAReport(doc_id=doc_id)
        for gate, detail, severity in failures:
            report.add(gate, detail, severity)

        first = report.to_dict()
        second = report.to_dict()
        self.assertEqual(first, second)
        self.assertEqual(first["passed"], report.is_ok)
        self.assertEqual(len(first["failures"]), len(failures))


if __name__ == "__main__":
    unittest.main()
