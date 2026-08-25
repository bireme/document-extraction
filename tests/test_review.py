"""Tests del flujo de revisión (criterios C1, C2, C3)."""

import unittest

from pdfsum.contract import SummaryResult
from pdfsum.review import (
    APPROVED,
    EDITED,
    PENDING,
    REJECTED,
    ReviewError,
    ReviewRecord,
    approve,
    edit_sections,
    reject,
)


def _good() -> SummaryResult:
    return SummaryResult(
        doc_id="d",
        idioma_principal="pt",
        tipo_documento="divulgacion",
        plantilla="C",
        secciones={
            "titulo": "Prevenção do tabagismo",
            "tipo_documento": "folheto",
            "entidad": "Ministério da Saúde",
            "publico": "população",
            "resumen_ejecutivo": "Resumo em português "
            "sobre a importância de parar de fumar e o Disque Saúde.",
            "puntos_clave": "- parar",
            "terminos": "tabagismo",
        },
    )


def _bad_schema() -> SummaryResult:
    r = _good()
    r.secciones["resumen_ejecutivo"] = ""  # fallo QA de error
    return r


class TestReview(unittest.TestCase):
    def test_estados(self):
        """C1: pending por defecto; transita a approved/rejected."""
        rec = ReviewRecord(doc_id="d")
        self.assertEqual(rec.state, PENDING)
        approve(rec, _good(), reviewer="ana", note="ok")
        self.assertEqual(rec.state, APPROVED)
        self.assertEqual(rec.reviewer, "ana")

        rec2 = reject(ReviewRecord(doc_id="d2"), reviewer="ana", note="mal OCR")
        self.assertEqual(rec2.state, REJECTED)
        self.assertEqual(len(rec2.history), 1)

    def test_edicion(self):
        """C2: editar cambia secciones concretas y marca 'edited'."""
        res = _good()
        rec = ReviewRecord(doc_id="d")
        res2, rec2 = edit_sections(res, rec, {"titulo": "Novo título"}, reviewer="bob")
        self.assertEqual(res2.secciones["titulo"], "Novo título")
        # el resto se preserva
        self.assertEqual(res2.secciones["entidad"], "Ministério da Saúde")
        self.assertEqual(rec2.state, EDITED)
        self.assertEqual(res2.meta["edited_by"], "bob")

    def test_no_aprobar_con_errores(self):
        """C3: no aprobar con fallos QA de error salvo force."""
        rec = ReviewRecord(doc_id="d")
        with self.assertRaises(ReviewError):
            approve(rec, _bad_schema(), reviewer="ana")
        # forzado sí, y queda registrado
        approve(rec, _bad_schema(), reviewer="ana", force=True)
        self.assertEqual(rec.state, APPROVED)
        self.assertIn("FORZADO", rec.note)


if __name__ == "__main__":
    unittest.main()
