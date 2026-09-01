"""Tests de arquitectura hexagonal de varias fases.

Verifican por AST que el dominio no importa adaptadores concretos, y que el
resumidor es un puerto (Protocol) que los adaptadores implementan.
"""

import ast
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "pdfsum"

# La CLI es la raíz de composición y, por definición, conecta puertos con
# adaptadores concretos. Toda otra excepción futura debe justificarse aquí.
DOMAIN_EXCEPTIONS = {"__init__.py", "cli.py"}

# Nombres de import prohibidos en el dominio.
FORBIDDEN = {
    "aiohttp",
    "httpx",
    "ollama",
    "requests",
    "socket",
    "subprocess",
    "urllib",
}
FORBIDDEN_LOCAL = "adapters"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod.split(".")[0])
            if FORBIDDEN_LOCAL in mod:
                names.add(FORBIDDEN_LOCAL)
    return names


def _domain_modules() -> list[Path]:
    """Descubre cada módulo de dominio sin depender de una lista manual."""
    return [
        path for path in sorted(SRC.glob("*.py")) if path.name not in DOMAIN_EXCEPTIONS
    ]


def _assert_protocol(test: unittest.TestCase, adapter, protocol) -> None:
    """Valida de forma reutilizable un adapter contra un Protocol runtime."""
    test.assertTrue(
        isinstance(adapter, protocol),
        f"{type(adapter).__name__} no cumple el puerto {protocol.__name__}",
    )


class TestArchitecture(unittest.TestCase):
    def test_c09_domain_has_no_adapter_imports(self):
        """C09 (F5): dominio no importa adaptadores ni procesos externos."""
        modules = _domain_modules()
        self.assertGreater(len(modules), 1)
        for module in modules:
            imps = _imports(module)
            bad = (imps & FORBIDDEN) | ({FORBIDDEN_LOCAL} & imps)
            self.assertFalse(
                bad,
                f"{module.name} importa dependencias prohibidas: {sorted(bad)}",
            )

    def test_summarizer_is_port(self):
        """C9 (F0): Summarizer es un Protocol y los adaptadores lo cumplen."""
        from pdfsum.adapters.fake_summarizer import FakeSummarizer
        from pdfsum.contract import Summarizer

        # runtime_checkable Protocol -> isinstance verifica la firma
        _assert_protocol(self, FakeSummarizer(), Summarizer)

    def test_transcriber_is_port(self):
        """C7 (F1): Transcriber es un Protocol y el adaptador fake lo cumple."""
        from pdfsum.adapters.fake_transcriber import FakeTranscriber
        from pdfsum.contract import Transcriber

        _assert_protocol(self, FakeTranscriber("x"), Transcriber)

    def test_pageocr_is_port(self):
        """C3 (F7): PageOCR es un Protocol y el adaptador fake lo cumple."""
        from pdfsum.adapters.fake_page_ocr import FakePageOCR
        from pdfsum.contract import PageOCR

        _assert_protocol(self, FakePageOCR(), PageOCR)


if __name__ == "__main__":
    unittest.main()
