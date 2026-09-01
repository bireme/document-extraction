"""Métricas agregadas de un lote (DOMINIO PURO).

Resume el resultado de procesar un lote: recuentos por tipo/idioma, calidad
(cuántos pasaron los QA gates) y tiempos. Solo agrega datos; no ejecuta nada.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .contract import SummaryResult
from .qa import QAReport


@dataclass
class BatchItem:
    """Un elemento procesado del lote: resultado + QA + tiempo."""

    result: SummaryResult
    qa: QAReport
    seconds: float = 0.0
    phase_seconds: dict[str, float] = field(default_factory=dict)
    cache_hit: bool = False


@dataclass
class BatchMetrics:
    total: int = 0
    ok: int = 0
    con_fallos: int = 0
    por_tipo: dict[str, int] = field(default_factory=dict)
    por_idioma: dict[str, int] = field(default_factory=dict)
    gates_fallados: dict[str, int] = field(default_factory=dict)
    tiempo_total: float = 0.0
    tiempo_medio: float = 0.0
    tiempo_total_por_fase: dict[str, float] = field(default_factory=dict)
    tiempo_medio_por_fase: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "ok": self.ok,
            "con_fallos": self.con_fallos,
            "por_tipo": self.por_tipo,
            "por_idioma": self.por_idioma,
            "gates_fallados": self.gates_fallados,
            "tiempo_total": round(self.tiempo_total, 3),
            "tiempo_medio": round(self.tiempo_medio, 3),
            "tiempo_total_por_fase": {
                phase: round(seconds, 6)
                for phase, seconds in self.tiempo_total_por_fase.items()
            },
            "tiempo_medio_por_fase": {
                phase: round(seconds, 6)
                for phase, seconds in self.tiempo_medio_por_fase.items()
            },
        }


def batch_metrics(items: list[BatchItem]) -> BatchMetrics:
    """Agrega métricas de una lista de elementos procesados."""
    m = BatchMetrics(total=len(items))
    tipos: Counter[str] = Counter()
    idiomas: Counter[str] = Counter()
    gates: Counter[str] = Counter()
    phases: Counter[str] = Counter()
    for it in items:
        if it.qa.is_ok:
            m.ok += 1
        else:
            m.con_fallos += 1
            for f in it.qa.failures:
                gates[f.gate] += 1
        tipos[it.result.tipo_documento] += 1
        idiomas[it.result.idioma_principal] += 1
        m.tiempo_total += it.seconds
        phases.update(it.phase_seconds)
    m.por_tipo = dict(tipos)
    m.por_idioma = dict(idiomas)
    m.gates_fallados = dict(gates)
    m.tiempo_medio = m.tiempo_total / m.total if m.total else 0.0
    m.tiempo_total_por_fase = dict(sorted(phases.items()))
    m.tiempo_medio_por_fase = {
        phase: seconds / m.total for phase, seconds in sorted(phases.items())
    }
    return m
