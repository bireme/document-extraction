"""Pruebas de métricas detalladas de GPU y Ollama."""

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pdfsum.adapters.observability import (
    InfrastructureMonitor,
    _gpu_metrics,
    _ollama_metrics,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return self.payload


class TestGpuMetrics(unittest.TestCase):
    @patch("pdfsum.adapters.observability.subprocess.run")
    def test_nvidia_smi_detallado_por_dispositivo(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    "0, GPU-abc, NVIDIA A100, 92, 7000, 8192, 79, "
                    "215.5, 250, N/A, 1410, 1215, P2\n"
                ),
            ),
            *[
                subprocess.CompletedProcess(
                    [],
                    0,
                    stdout=("0, 0x0000000000000004\n" if index == 0 else "0, 0\n"),
                )
                for index in range(4)
            ],
        ]

        observation = _gpu_metrics()

        self.assertTrue(observation["available"])
        gpu = observation["devices"][0]
        self.assertEqual(gpu["uuid"], "GPU-abc")
        self.assertEqual(gpu["memory_used_mb"], 7000)
        self.assertEqual(gpu["power_draw_w"], 215.5)
        self.assertIsNone(gpu["fan_speed_percent"])
        self.assertTrue(gpu["throttling_active"])

    @patch("pdfsum.adapters.observability.subprocess.run")
    def test_nvidia_smi_ausente_deja_motivo(self, run):
        run.side_effect = FileNotFoundError()

        observation = _gpu_metrics()

        self.assertFalse(observation["available"])
        self.assertEqual(observation["error"], "nvidia-smi no encontrado")

    @patch("pdfsum.adapters.observability.subprocess.run")
    def test_nvidia_smi_degrada_a_campos_basicos(self, run):
        run.side_effect = [
            subprocess.CalledProcessError(1, ["nvidia-smi"]),
            subprocess.CompletedProcess(
                [], 0, stdout="0, GPU-old, NVIDIA T4, 80, 12000, 15360, 72\n"
            ),
            *[subprocess.CompletedProcess([], 0, stdout="0, 0\n") for _ in range(4)],
        ]

        observation = _gpu_metrics()

        self.assertTrue(observation["available"])
        self.assertEqual(observation["detail_level"], "basic")
        self.assertEqual(observation["devices"][0]["memory_used_mb"], 12000)
        self.assertIsNone(observation["devices"][0]["power_draw_w"])


class TestOllamaMetrics(unittest.TestCase):
    @patch("pdfsum.adapters.observability.urllib.request.urlopen")
    def test_api_ps_informa_vram_y_modelo(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "models": [
                    {
                        "name": "qwen2.5:7b",
                        "size": 6 * 1024**3,
                        "size_vram": 5 * 1024**3,
                        "context_length": 8192,
                        "details": {
                            "parameter_size": "7.6B",
                            "quantization_level": "Q4_K_M",
                        },
                    }
                ]
            }
        )

        observation = _ollama_metrics("http://secret@ollama:11434")

        self.assertTrue(observation["available"])
        self.assertEqual(observation["host"], "http://ollama:11434")
        self.assertEqual(observation["models"][0]["size_vram_mb"], 5120)
        self.assertEqual(observation["models"][0]["context_length"], 8192)


class TestGpuSummary(unittest.TestCase):
    @patch("pdfsum.adapters.observability.collect_snapshot")
    def test_muestra_incluye_run_documento_y_fase(self, collect):
        collect.return_value = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "process": {"cpu_seconds": 1.0},
            "host": {},
            "gpu": {"available": False, "devices": []},
        }
        with TemporaryDirectory() as td:
            path = Path(td) / "infra.jsonl"
            monitor = InfrastructureMonitor(
                path, Path(td), ollama_host="", run_id="run-123"
            )
            monitor.set_context(doc_id="doc-7", phase="resumen")

            monitor.sample()

            sample = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sample["run_id"], "run-123")
        self.assertEqual(sample["doc_id"], "doc-7")
        self.assertEqual(sample["phase"], "resumen")

    def test_resumen_combina_gpu_fisica_y_vram_de_ollama(self):
        with TemporaryDirectory() as td:
            monitor = InfrastructureMonitor(
                Path(td) / "infra.jsonl", Path(td), ollama_host=""
            )
            monitor._samples = [
                {
                    "process": {"cpu_seconds": 1.0},
                    "host": {},
                    "gpu": {"available": True},
                    "gpus": [
                        {
                            "index": 0,
                            "uuid": "GPU-abc",
                            "name": "NVIDIA A100",
                            "utilization_percent": 92.0,
                            "memory_used_mb": 7000.0,
                            "memory_total_mb": 8192.0,
                            "temperature_c": 79.0,
                            "power_draw_w": 215.5,
                            "power_limit_w": 250.0,
                            "fan_speed_percent": None,
                            "clock_sm_mhz": 1410.0,
                            "clock_memory_mhz": 1215.0,
                            "throttling_active": True,
                        }
                    ],
                    "ollama": {
                        "available": True,
                        "host": "http://ollama:11434",
                        "models": [
                            {
                                "name": "qwen2.5:7b",
                                "size_vram_mb": 5120.0,
                                "context_length": 8192,
                                "parameter_size": "7.6B",
                                "quantization_level": "Q4_K_M",
                            }
                        ],
                    },
                }
            ]

            summary = monitor.summary()

        gpu = summary["gpu_monitoring"]
        self.assertTrue(gpu["nvidia_smi_available"])
        self.assertTrue(gpu["ollama_api_available"])
        self.assertTrue(gpu["ollama_metrics_enabled"])
        self.assertEqual(gpu["ollama_vram_loaded_peak_mb"], 5120)
        self.assertEqual(gpu["ollama_models"][0]["name"], "qwen2.5:7b")
        self.assertTrue(gpu["devices"][0]["throttling_detected"])
        self.assertEqual(summary["gpu_power_draw_max_w"], 215.5)


if __name__ == "__main__":
    unittest.main()
