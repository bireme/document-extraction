"""FASE20 regression guard: suite no falla si fastapi no está instalado.

Simula un entorno sin FastAPI bloqueando `import fastapi` con un import-hook
antes de ejecutar unittest discovery. Los tests de servicio deben quedar
SKIPPED, no ERROR.
"""

import builtins
import io
import sys
import unittest
from unittest import mock


class TestServiceTestsSkipWithoutFastapi(unittest.TestCase):
    def test_suite_no_falla_sin_fastapi(self):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("fastapi"):
                raise ImportError("simulado")
            return real_import(name, *args, **kwargs)

        stream = io.StringIO()
        loader = unittest.TestLoader()

        # Solo los módulos de servicio (evita recursión al descubrir este test).
        names = [
            "tests.test_api_service",
            "tests.test_api_security",
            "tests.test_worker",
        ]

        # Forzar re-import bajo el hook (si se ejecutó antes en la suite).
        saved: dict[str, object] = {}
        for key in list(sys.modules):
            if key.startswith("fastapi") or key in names:
                saved[key] = sys.modules.get(key)  # type: ignore[assignment]
                sys.modules.pop(key, None)

        try:
            with mock.patch("builtins.__import__", side_effect=fake_import):
                suite = unittest.TestSuite(
                    loader.loadTestsFromName(n) for n in names
                )
                result = unittest.TextTestRunner(stream=stream, verbosity=0).run(
                    suite
                )
        finally:
            for key, mod in saved.items():
                if mod is not None:
                    sys.modules[key] = mod  # type: ignore[assignment]

        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        # Al menos un skip: los tests del servicio.
        self.assertGreater(len(result.skipped), 0)


if __name__ == "__main__":
    unittest.main()
