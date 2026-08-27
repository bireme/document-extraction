"""Tests del dominio bibframe.py (criterios C3, C4, FASE15)."""

import unittest

from pdfsum.bibframe import (
    has_minimum_data,
    merge_bib_sources,
    to_bibframe,
)
from pdfsum.contract import SummaryResult


def _summary(**kw) -> SummaryResult:
    base = {
        "doc_id": "doc1",
        "idioma_principal": "es",
        "tipo_documento": "divulgacion",
        "plantilla": "C",
        "secciones": {
            "titulo": "Título del resumen",
            "entidad": "Editorial Ciencias Médicas",
            "terminos": "- Laparoscopia\n- Nefrectomía",
        },
        "meta": {"pages": 14},
    }
    base.update(kw)
    return SummaryResult(**base)


class TestMergePrecedencia(unittest.TestCase):
    def test_pdf_metadata_tiene_precedencia(self):
        pdf_meta = {
            "title": "Urología",
            "subject": "Capítulo 10. Laparoscopia",
            "author": "René Salas Cabrera",
            "creation_date": "Wed May  2 10:44:32 2012 EDT",
            "pages": 14,
        }
        bib = merge_bib_sources(pdf_meta, _summary())
        self.assertEqual(bib.title, "Urología")
        self.assertEqual(bib.sources["title"], "pdf_metadata")
        self.assertEqual(bib.authors, ["René Salas Cabrera"])
        self.assertEqual(bib.date, "2012")
        self.assertEqual(bib.section_title, "Capítulo 10. Laparoscopia")

    def test_resumen_complementa_sin_pdf(self):
        bib = merge_bib_sources(None, _summary())
        self.assertEqual(bib.title, "Título del resumen")
        self.assertEqual(bib.sources["title"], "summary")
        self.assertEqual(bib.publisher, "Editorial Ciencias Médicas")
        self.assertEqual(bib.language, "es")
        self.assertEqual(bib.pages, 14)
        self.assertIn("Laparoscopia", bib.subjects)

    def test_entidad_no_especificada_no_es_dato(self):
        s = _summary(
            secciones={
                "titulo": "T",
                "entidad": "No se especifica una entidad en el texto.",
            }
        )
        bib = merge_bib_sources(None, s)
        self.assertEqual(bib.publisher, "")
        self.assertNotIn("publisher", bib.sources)

    def test_autores_multiples_divididos(self):
        pdf_meta = {"title": "T", "author": "Ana Pérez; Luis Ruiz y José Gil"}
        bib = merge_bib_sources(pdf_meta, _summary())
        self.assertEqual(bib.authors, ["Ana Pérez", "Luis Ruiz", "José Gil"])


class TestDatoMinimo(unittest.TestCase):
    def test_sin_titulo_no_hay_registro(self):
        s = _summary(secciones={})
        bib = merge_bib_sources(None, s)
        self.assertFalse(has_minimum_data(bib))

    def test_con_titulo_de_cualquier_fuente_si(self):
        self.assertTrue(has_minimum_data(merge_bib_sources(None, _summary())))
        s_vacio = _summary(secciones={})
        self.assertTrue(has_minimum_data(merge_bib_sources({"title": "X"}, s_vacio)))


class TestJsonLd(unittest.TestCase):
    def _record(self):
        pdf_meta = {
            "title": "Urología",
            "subject": "Capítulo 10. Laparoscopia",
            "author": "René Salas Cabrera",
            "creation_date": "2012",
            "pages": 14,
        }
        return to_bibframe(merge_bib_sources(pdf_meta, _summary()))

    def test_context_y_graph(self):
        rec = self._record()
        self.assertEqual(
            rec["@context"]["bf"], "http://id.loc.gov/ontologies/bibframe/"
        )
        types = [n["@type"] for n in rec["@graph"]]
        self.assertEqual(types, ["bf:Work", "bf:Instance"])

    def test_instance_enlaza_al_work(self):
        rec = self._record()
        work, instance = rec["@graph"]
        self.assertEqual(instance["bf:instanceOf"]["@id"], work["@id"])
        self.assertIn("doc1", work["@id"])  # doc_id trazable

    def test_titulo_idioma_autores_materias(self):
        rec = self._record()
        work = rec["@graph"][0]
        self.assertEqual(work["bf:title"]["bf:mainTitle"], "Urología")
        self.assertTrue(work["bf:language"]["@id"].endswith("/spa"))
        agents = [c["bf:agent"]["rdfs:label"] for c in work["bf:contribution"]]
        self.assertEqual(agents, ["René Salas Cabrera"])
        subjects = [s["rdfs:label"] for s in work["bf:subject"]]
        self.assertIn("Laparoscopia", subjects)

    def test_instance_extent_fecha_capitulo(self):
        rec = self._record()
        instance = rec["@graph"][1]
        self.assertEqual(instance["bf:extent"]["rdfs:label"], "14 páginas")
        self.assertEqual(instance["bf:provisionActivity"]["bf:date"], "2012")
        self.assertEqual(
            instance["bf:title"]["bf:mainTitle"], "Capítulo 10. Laparoscopia"
        )

    def test_bloque_pdfsum_draft_con_fuentes(self):
        rec = self._record()
        meta = rec["_pdfsum"]
        self.assertEqual(meta["status"], "draft")
        self.assertEqual(meta["doc_id"], "doc1")
        self.assertEqual(meta["sources"]["title"], "pdf_metadata")
        self.assertIn("revisión humana", meta["note"])

    def test_campos_ausentes_no_emiten_claves(self):
        s = _summary(secciones={"titulo": "Solo título"}, meta={})
        rec = to_bibframe(merge_bib_sources(None, s))
        work, instance = rec["@graph"]
        self.assertNotIn("bf:contribution", work)
        self.assertNotIn("bf:subject", work)
        self.assertNotIn("bf:extent", instance)
        self.assertNotIn("bf:provisionActivity", instance)


if __name__ == "__main__":
    unittest.main()
