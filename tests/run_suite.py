"""Ejecutor sencillo con resumen uniforme por categoría de prueba."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT))
INTEGRATION_MODULES = {
    "test_api.py",
    "test_batch_pdf.py",
    "test_batch_runner_errors.py",
    "test_cli.py",
    "test_cli_batch.py",
    "test_cli_run.py",
    "test_hybrid_ocr.py",
    "test_hybrid_seg.py",
    "test_packaging.py",
}
SPECIAL_MODULES = INTEGRATION_MODULES | {"test_architecture.py"}


def _load_modules(paths: list[Path]) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for path in paths:
        suite.addTests(loader.loadTestsFromName(f"tests.{path.stem}"))
    return suite


def load_suite(name: str) -> unittest.TestSuite:
    """Carga una categoría sin mezclar suites lentas u opcionales."""
    loader = unittest.defaultTestLoader
    if name == "all":
        return loader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(ROOT))
    if name == "unit":
        paths = [
            path
            for path in sorted(TESTS.glob("test_*.py"))
            if path.name not in SPECIAL_MODULES
        ]
        return _load_modules(paths)
    if name == "integration":
        return _load_modules(
            [TESTS / filename for filename in sorted(INTEGRATION_MODULES)]
        )
    if name == "architecture":
        return _load_modules([TESTS / "test_architecture.py"])
    if name == "performance":
        os.environ["PDFSUM_RUN_PERFORMANCE"] = "1"
    start = TESTS / name
    return loader.discover(str(start), pattern="test_*.py", top_level_dir=str(ROOT))


def _coverage_totals(coverage_instance) -> tuple[float, float]:
    handle, filename = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    try:
        coverage_instance.json_report(outfile=filename)
        totals = json.loads(Path(filename).read_text(encoding="utf-8"))["totals"]
    finally:
        Path(filename).unlink(missing_ok=True)
    return (
        totals["percent_statements_covered"],
        totals["percent_branches_covered"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ejecuta una categoría y muestra un resumen uniforme."
    )
    parser.add_argument(
        "suite",
        choices=(
            "unit",
            "integration",
            "contract",
            "architecture",
            "e2e",
            "performance",
            "all",
        ),
    )
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args()
    coverage_instance = None
    if args.coverage:
        try:
            import coverage
        except ModuleNotFoundError as exc:
            parser.error(f"coverage no está instalado: {exc}")
        coverage_instance = coverage.Coverage(branch=True, source=["pdfsum"])
        coverage_instance.start()

    started = time.perf_counter()
    stream = io.StringIO()
    with redirect_stdout(stream), redirect_stderr(stream):
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(
            load_suite(args.suite)
        )
    duration = time.perf_counter() - started
    line_coverage = branch_coverage = None
    if coverage_instance is not None:
        coverage_instance.stop()
        coverage_instance.save()
        line_coverage, branch_coverage = _coverage_totals(coverage_instance)

    failed_ids = {
        test.id().split(" (", 1)[0] for test, _ in [*result.failures, *result.errors]
    }
    failed = len(failed_ids) + len(result.unexpectedSuccesses)
    passed = (
        result.testsRun - failed - len(result.skipped) - len(result.expectedFailures)
    )
    print("Resumen de pruebas")
    print("-------------------")
    print(f"Suite: {args.suite}")
    print(f"Ejecutadas: {result.testsRun}")
    print(f"Exitosas: {passed}")
    print(f"Fallidas: {failed}")
    print(f"Omitidas: {len(result.skipped)}")
    print(f"Duración: {duration:.2f} s")
    if line_coverage is not None and branch_coverage is not None:
        print("\nCobertura:")
        print(f"Líneas: {line_coverage:.1f}%")
        print(f"Branches: {branch_coverage:.1f}%")
    print(f"\nResultado: {'OK' if result.wasSuccessful() else 'FALLÓ'}")
    problems = [*result.failures, *result.errors]
    if problems:
        print("\nFallos:")
        for test, traceback in problems:
            reason = next(
                (
                    line.strip()
                    for line in reversed(traceback.splitlines())
                    if line.strip()
                ),
                "motivo no disponible",
            )
            print(f"- {test.id()}\n  Motivo: {reason}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
