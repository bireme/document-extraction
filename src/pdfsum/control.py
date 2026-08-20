"""Set de control y métricas de cobertura (DOMINIO PURO).

Permite evaluar resultados contra casos de control fijos (ground-truth ligero):
idioma esperado, tipo esperado y términos que deberían aparecer. Produce
veredictos y un reporte agregado para seguimiento de calidad por lote.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .contract import SummaryResult


@dataclass
class ControlCase:
    """Caso de control: expectativas verificables sobre un documento."""

    doc_id: str
    expected_lang: str = ""
    expected_type: str = ""
    expected_terms: list[str] = field(default_factory=list)


@dataclass
class CaseVerdict:
    doc_id: str
    coverage: float = 0.0
    lang_ok: bool = True
    type_ok: bool = True
    missing_terms: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.lang_ok and self.type_ok and not self.missing_terms

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id, "coverage": round(self.coverage, 3),
            "lang_ok": self.lang_ok, "type_ok": self.type_ok,
            "missing_terms": self.missing_terms, "passed": self.passed,
        }


def term_coverage(text: str, expected_terms: list[str]) -> tuple[float, list[str]]:
    """Fracción de términos esperados presentes (case-insensitive) + faltantes."""
    if not expected_terms:
        return 1.0, []
    low = text.lower()
    missing = [t for t in expected_terms if t.lower() not in low]
    present = len(expected_terms) - len(missing)
    return present / len(expected_terms), missing


def _all_text(res: SummaryResult) -> str:
    return "\n".join(res.secciones.values())


def evaluate_case(res: SummaryResult, case: ControlCase) -> CaseVerdict:
    """Compara un resultado contra su caso de control."""
    cov, missing = term_coverage(_all_text(res), case.expected_terms)
    return CaseVerdict(
        doc_id=case.doc_id,
        coverage=cov,
        lang_ok=(not case.expected_lang
                 or res.idioma_principal == case.expected_lang),
        type_ok=(not case.expected_type
                 or res.tipo_documento == case.expected_type),
        missing_terms=missing,
    )


@dataclass
class ControlReport:
    total: int = 0
    passed: int = 0
    coverage_media: float = 0.0
    lang_aciertos: int = 0
    type_aciertos: int = 0
    verdicts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total, "passed": self.passed,
            "coverage_media": round(self.coverage_media, 3),
            "lang_aciertos": self.lang_aciertos,
            "type_aciertos": self.type_aciertos,
            "verdicts": self.verdicts,
        }


def run_control_suite(
    results: dict[str, SummaryResult], cases: list[ControlCase]
) -> ControlReport:
    """Evalúa una lista de casos contra sus resultados (por doc_id)."""
    rep = ControlReport(total=len(cases))
    cov_sum = 0.0
    for case in cases:
        res = results.get(case.doc_id)
        if res is None:
            rep.verdicts.append(
                {"doc_id": case.doc_id, "error": "sin resultado"})
            continue
        v = evaluate_case(res, case)
        cov_sum += v.coverage
        if v.passed:
            rep.passed += 1
        if v.lang_ok:
            rep.lang_aciertos += 1
        if v.type_ok:
            rep.type_aciertos += 1
        rep.verdicts.append(v.to_dict())
    rep.coverage_media = cov_sum / rep.total if rep.total else 0.0
    return rep
