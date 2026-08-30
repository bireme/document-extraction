"""Errores, reintentos e interrupciones del adapter de lotes de texto."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pdfsum.adapters.batch_runner import run_batch
from pdfsum.adapters.fake_summarizer import FakeSummarizer


class _FailingSummarizer:
    def summarize(self, request):
        raise TimeoutError("servicio de resumen demorado")


class _EmptySummarizer:
    def summarize(self, request):
        return {}


class _InterruptingSummarizer:
    def summarize(self, request):
        raise KeyboardInterrupt()


class TestBatchRunnerErrors(unittest.TestCase):
    def test_directorio_inexistente_produce_lote_vacio_valido(self):
        """Una entrada ausente no inventa documentos ni rompe el reporte."""
        with TemporaryDirectory() as td:
            output = Path(td) / "salida"
            report = run_batch(
                str(Path(td) / "no_existe"), str(output), FakeSummarizer()
            )
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["progress"]["discovered"], 0)
            self.assertEqual(
                json.loads((output / "report.json").read_text(encoding="utf-8"))[
                    "status"
                ],
                "completed",
            )

    def test_timeout_del_summarizer_agota_reintentos_y_aisla_fallo(self):
        """El error externo queda truncado, contabilizado y no se vuelve éxito."""
        with TemporaryDirectory() as td:
            input_dir = Path(td) / "entrada"
            output = Path(td) / "salida"
            input_dir.mkdir()
            (input_dir / "uno.txt").write_text("contenido", encoding="utf-8")
            report = run_batch(
                str(input_dir), str(output), _FailingSummarizer(), max_retries=1
            )
            document = report["documents"][0]
            self.assertEqual(report["status"], "completed_with_errors")
            self.assertEqual(document["status"], "failed")
            self.assertEqual(document["attempts"], 2)
            self.assertIn("TimeoutError", document["error"])
            self.assertFalse((output / "uno.json").exists())

    def test_respuesta_vacia_completa_con_qa_fallido(self):
        """Un payload vacío queda visible mediante gates de QA."""
        with TemporaryDirectory() as td:
            input_dir = Path(td) / "entrada"
            output = Path(td) / "salida"
            input_dir.mkdir()
            (input_dir / "uno.txt").write_text("contenido", encoding="utf-8")
            report = run_batch(str(input_dir), str(output), _EmptySummarizer())
            document = report["documents"][0]
            self.assertEqual(document["status"], "completed")
            self.assertFalse(document["qa_ok"])
            self.assertIn("schema", document["gates"])

    def test_archivo_sin_permiso_logico_se_registra_y_lote_continua(self):
        """Un PermissionError de lectura queda aislado por documento."""
        with TemporaryDirectory() as td:
            input_dir = Path(td) / "entrada"
            output = Path(td) / "salida"
            input_dir.mkdir()
            target = input_dir / "uno.txt"
            target.write_text("contenido", encoding="utf-8")
            original = Path.read_text

            def denied(path, *args, **kwargs):
                if path == target:
                    raise PermissionError("lectura denegada")
                return original(path, *args, **kwargs)

            with patch.object(Path, "read_text", side_effect=denied, autospec=True):
                report = run_batch(str(input_dir), str(output), FakeSummarizer())
            self.assertEqual(report["status"], "completed_with_errors")
            self.assertIn("PermissionError", report["documents"][0]["error"])

    def test_interrupcion_durante_summary_deja_checkpoint_valido(self):
        """KeyboardInterrupt publica estado interrupted y conserva JSON válido."""
        with TemporaryDirectory() as td:
            input_dir = Path(td) / "entrada"
            output = Path(td) / "salida"
            input_dir.mkdir()
            (input_dir / "uno.txt").write_text("contenido", encoding="utf-8")
            with self.assertRaises(KeyboardInterrupt):
                run_batch(str(input_dir), str(output), _InterruptingSummarizer())
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
