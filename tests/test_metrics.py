"""Tests de métricas de lote (criterio C9)."""
import unittest

from pdfsum.contract import SummaryResult
from pdfsum.metrics import BatchItem, batch_metrics
from pdfsum.qa import check_result


def _res(doc_id, tipo, idioma):
    return SummaryResult(
        doc_id=doc_id, idioma_principal=idioma, tipo_documento=tipo,
        plantilla="C",
        secciones={
            "titulo": "T", "tipo_documento": "folheto", "entidad": "MS",
            "publico": "geral",
            "resumen_ejecutivo": "Resumo suficientemente longo em português "
                                 "para o gate de idioma funcionar bem.",
            "puntos_clave": "- a", "terminos": "x",
        },
    )


class TestMetrics(unittest.TestCase):
    def test_batch_metrics(self):
        """C9: agrega total/ok/fallos/por_tipo/por_idioma/tiempos."""
        r1 = _res("a", "articulo", "pt")
        r2 = _res("b", "divulgacion", "pt")
        r3 = _res("c", "divulgacion", "en")
        r3.secciones["resumen_ejecutivo"] = ""  # provoca fallo schema

        items = [
            BatchItem(r1, check_result(r1), 1.0),
            BatchItem(r2, check_result(r2), 2.0),
            BatchItem(r3, check_result(r3), 3.0),
        ]
        m = batch_metrics(items)
        self.assertEqual(m.total, 3)
        self.assertEqual(m.ok, 2)
        self.assertEqual(m.con_fallos, 1)
        self.assertEqual(m.por_tipo["divulgacion"], 2)
        self.assertEqual(m.por_idioma["pt"], 2)
        self.assertEqual(m.tiempo_total, 6.0)
        self.assertEqual(m.tiempo_medio, 2.0)
        self.assertIn("schema", m.gates_fallados)


if __name__ == "__main__":
    unittest.main()
