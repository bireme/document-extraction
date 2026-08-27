"""Tests del flag --backend en la CLI (criterio C5, FASE14).

Comportamiento por defecto (sin --backend/env/config) debe ser idéntico al
de antes de esta fase: ollama + qwen2.5:7b. Cero regresión.
"""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pdfsum.cli import _resolve_backend_model, main


class TestResolveBackendModelDefaults(unittest.TestCase):
    def test_default_identico_a_antes_de_fase14(self):
        with patch.dict("os.environ", {}, clear=True):
            backend, model = _resolve_backend_model(None, None)
        self.assertEqual(backend, "ollama")
        self.assertEqual(model, "qwen2.5:7b")

    def test_flag_backend_prevalece_sobre_env(self):
        with patch.dict("os.environ", {"PDFSUM_SUMMARIZER_BACKEND": "openai"}):
            backend, model = _resolve_backend_model("anthropic", None)
        self.assertEqual(backend, "anthropic")
        self.assertEqual(model, "claude-haiku-4-5")

    def test_flag_model_prevalece_sobre_default(self):
        backend, model = _resolve_backend_model("openrouter", "mi-modelo-custom")
        self.assertEqual(backend, "openrouter")
        self.assertEqual(model, "mi-modelo-custom")


class TestCliDryRunConBackendCloud(unittest.TestCase):
    def test_summarize_dry_run_ignora_backend_cloud_sin_api_key(self):
        """--dry-run usa FakeSummarizer sin importar el backend (no llama red)."""
        with TemporaryDirectory() as td, patch.dict("os.environ", {}, clear=True):
            txt = Path(td) / "doc.txt"
            txt.write_text("RESUMO\nObjetivo: x.\nABSTRACT\nObjective: x.\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        "summarize",
                        "--text",
                        str(txt),
                        "--backend",
                        "openai",
                        "--dry-run",
                    ]
                )
            self.assertEqual(rc, 0)

    def test_backend_desconocido_rechazado_por_argparse(self):
        with (
            self.assertRaises(SystemExit),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            main(["doctor", "--backend", "acme-no-existe"])


if __name__ == "__main__":
    unittest.main()
