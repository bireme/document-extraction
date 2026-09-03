"""FASE20 C8: el core importa sin fastapi; modo servicio da mensaje claro."""

import builtins
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfsum.adapters import api_service


class TestOptionalDeps(unittest.TestCase):
    def test_create_app_sin_fastapi_falla_con_mensaje(self):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "fastapi":
                raise ImportError("simulado")
            return real_import(name, *args, **kwargs)

        with (
            tempfile.TemporaryDirectory() as td,
            patch("builtins.__import__", side_effect=fake_import),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                api_service.create_app(Path(td) / "ws", token="t")
            self.assertIn("pdfsum[service]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
