"""Pruebas de robustez, atomicidad y concurrencia del filesystem."""

import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pdfsum.adapters.job_store import FileJobStore
from pdfsum.adapters.observability import EventLog, atomic_write_json


class TestAtomicWriteJson(unittest.TestCase):
    def test_escrituras_concurrentes_no_corrompen_el_json(self):
        """Cada escritura concurrente publica un documento JSON completo."""
        with TemporaryDirectory() as td:
            path = Path(td) / "report.json"
            barrier = threading.Barrier(8)

            def write(index: int) -> None:
                barrier.wait()
                atomic_write_json(path, {"indice": index, "texto": "ñ" * 1000})

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(write, index) for index in range(8)]
                errors = [future.exception() for future in futures]

            self.assertEqual(errors, [None] * 8)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(payload["indice"], range(8))
            self.assertEqual(payload["texto"], "ñ" * 1000)

    def test_interrupcion_antes_del_replace_preserva_el_reporte_valido(self):
        """Un fallo de publicación no sustituye el último reporte válido."""
        with TemporaryDirectory() as td:
            path = Path(td) / "report.json"
            atomic_write_json(path, {"estado": "válido"})

            with (
                patch(
                    "pdfsum.adapters.observability.os.replace",
                    side_effect=KeyboardInterrupt(),
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                atomic_write_json(path, {"estado": "parcial"})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"estado": "válido"},
            )


class TestEventLog(unittest.TestCase):
    def test_eventos_concurrentes_forman_lineas_json_validas(self):
        """El lock del log evita líneas mezcladas entre threads."""
        with TemporaryDirectory() as td:
            path = Path(td) / "eventos.jsonl"
            log = EventLog(path, "corrida-1")
            with ThreadPoolExecutor(max_workers=6) as executor:
                list(
                    executor.map(
                        lambda index: log.write("paso", indice=index), range(60)
                    )
                )

            lines = path.read_text(encoding="utf-8").splitlines()
            records = [json.loads(line) for line in lines]
            self.assertEqual(len(records), 60)
            self.assertEqual({record["indice"] for record in records}, set(range(60)))


class TestFileJobStore(unittest.TestCase):
    def test_json_vacio_o_corrupto_se_rechaza_claramente(self):
        """Un estado inválido nunca se interpreta como una cola vacía válida."""
        with TemporaryDirectory() as td:
            path = Path(td) / "jobs.json"
            for content in ("", '{"job":'):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(json.JSONDecodeError):
                        FileJobStore(str(path))

    def test_nombres_unicode_espacios_y_puntos_persisten(self):
        """Las claves legítimas conservan Unicode, espacios y múltiples puntos."""
        with TemporaryDirectory() as td:
            path = Path(td) / "cola con espacios.json"
            store = FileJobStore(str(path))
            key = "informe clínico.v2.final"
            store.put(key, {"estado": "listo"})

            restored = FileJobStore(str(path))
            self.assertEqual(restored.get(key), {"estado": "listo"})

    def test_escrituras_concurrentes_preservan_todos_los_jobs(self):
        """Los puts simultáneos no pierden claves ni publican JSON parcial."""
        with TemporaryDirectory() as td:
            path = Path(td) / "jobs.json"
            store = FileJobStore(str(path))
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(
                    executor.map(
                        lambda index: store.put(
                            f"documento-{index}", {"indice": index}
                        ),
                        range(40),
                    )
                )

            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(store.all()), 40)
            self.assertEqual(len(persisted), 40)
            self.assertEqual(persisted["documento-39"], {"indice": 39})


if __name__ == "__main__":
    unittest.main()
