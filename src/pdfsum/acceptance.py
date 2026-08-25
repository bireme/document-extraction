"""Verificación de aceptación contra un set de control (DOMINIO PURO).

Permite a un tercero confirmar que su instalación produce resultados SIMILARES
(no idénticos: el LLM es no determinista). Se apoya en el set de control de la
Fase 4: cobertura de términos esperados + acierto de idioma y tipo.

Un lote PASA la aceptación si la cobertura media supera un umbral y todos los
casos aciertan idioma y tipo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .control import ControlCase

DEFAULT_MIN_COVERAGE = 0.6


def load_control_set(path: str) -> list[ControlCase]:
    """Carga un set de control desde JSON (lista de casos)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        ControlCase(
            doc_id=c["doc_id"],
            expected_lang=c.get("expected_lang", ""),
            expected_type=c.get("expected_type", ""),
            expected_terms=list(c.get("expected_terms", [])),
        )
        for c in data
    ]


@dataclass
class AcceptanceVerdict:
    passed: bool
    coverage_media: float
    lang_ok: bool
    type_ok: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "coverage_media": round(self.coverage_media, 3),
            "lang_ok": self.lang_ok,
            "type_ok": self.type_ok,
            "detail": self.detail,
        }


def acceptance_verdict(
    control_report: dict, min_coverage: float = DEFAULT_MIN_COVERAGE
) -> AcceptanceVerdict:
    """Decide PASS/FAIL a partir del reporte de run_control_suite().to_dict()."""
    total = control_report.get("total", 0)
    cov = control_report.get("coverage_media", 0.0)
    lang_ok = control_report.get("lang_aciertos", 0) == total
    type_ok = control_report.get("type_aciertos", 0) == total
    cov_ok = cov >= min_coverage
    passed = bool(total) and cov_ok and lang_ok and type_ok
    detail = (
        f"cobertura media {cov:.2f} (umbral {min_coverage:.2f}: "
        f"{'ok' if cov_ok else 'BAJO'}); idioma {'ok' if lang_ok else 'FALLA'}; "
        f"tipo {'ok' if type_ok else 'FALLA'}"
    )
    return AcceptanceVerdict(passed, cov, lang_ok, type_ok, detail)
