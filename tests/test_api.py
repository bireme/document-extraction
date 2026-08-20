"""Tests de la API de consulta (criterios C8, C9, C10)."""
import json
import unittest
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from pdfsum.adapters.api_server import make_handler


def _write_batch(d: Path) -> None:
    (d / "art.json").write_text(json.dumps({
        "doc_id": "art", "idioma_principal": "pt", "tipo_documento": "articulo",
        "plantilla": "A", "secciones": {"titulo": "T"},
        "idiomas_resumo_origem": [], "abstracts_origem": [], "meta": {},
        "_qa": {"passed": True, "failures": []},
    }), encoding="utf-8")
    (d / "report.json").write_text(json.dumps({
        "metrics": {"total": 1, "ok": 1}, "queue": {"done": 1},
        "documents": [{"doc_id": "art"}],
    }), encoding="utf-8")


class TestAPI(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.dir = Path(self._td.name)
        _write_batch(self.dir)
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(str(self.dir)))
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._td.cleanup()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_list_summaries(self):
        """C8: GET /api/summaries lista los resúmenes."""
        status, data = self._get("/api/summaries")
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["doc_id"], "art")
        self.assertTrue(data[0]["qa_ok"])

    def test_get_summary(self):
        """C9: GET /api/summaries/<id> devuelve detalle; 404 si no existe."""
        status, data = self._get("/api/summaries/art")
        self.assertEqual(status, 200)
        self.assertEqual(data["tipo_documento"], "articulo")
        # inexistente -> 404
        try:
            self._get("/api/summaries/nope")
            self.fail("esperaba HTTPError 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_get_report(self):
        """C10: GET /api/report devuelve el reporte del lote."""
        status, data = self._get("/api/report")
        self.assertEqual(status, 200)
        self.assertEqual(data["metrics"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
