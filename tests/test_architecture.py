"""Tests de arquitectura hexagonal (criterios C8, C9).

Verifican por AST que el dominio no importa adaptadores concretos, y que el
resumidor es un puerto (Protocol) que los adaptadores implementan.
"""
import ast
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "pdfsum"

# Módulos de dominio puro (no deben tocar adaptadores/procesos externos).
DOMAIN_MODULES = ["contract.py", "classify.py", "abstracts.py",
                  "templates.py", "pipeline.py", "excerpt.py",
                  "qa.py", "metrics.py", "queue.py",
                  "review.py", "export.py", "chunking.py", "control.py", "workspace.py", "acceptance.py"]

# Nombres de import prohibidos en el dominio.
FORBIDDEN = {"ollama", "requests", "urllib", "subprocess", "socket", "httpx"}
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


class TestArchitecture(unittest.TestCase):
    def test_domain_has_no_adapter_imports(self):
        """C8: dominio no importa adaptadores ni procesos externos."""
        for mod in DOMAIN_MODULES:
            imps = _imports(SRC / mod)
            bad = (imps & FORBIDDEN) | ({FORBIDDEN_LOCAL} & imps)
            self.assertFalse(
                bad, f"{mod} importa dependencias prohibidas: {bad}")

    def test_summarizer_is_port(self):
        """C9: Summarizer es un Protocol y los adaptadores lo cumplen."""
        from pdfsum.adapters.fake_summarizer import FakeSummarizer
        from pdfsum.contract import Summarizer

        # runtime_checkable Protocol -> isinstance verifica la firma
        self.assertTrue(isinstance(FakeSummarizer(), Summarizer))

    def test_transcriber_is_port(self):
        """C7 (F1): Transcriber es un Protocol y el adaptador fake lo cumple."""
        from pdfsum.adapters.fake_transcriber import FakeTranscriber
        from pdfsum.contract import Transcriber

        self.assertTrue(isinstance(FakeTranscriber("x"), Transcriber))


if __name__ == "__main__":
    unittest.main()
