"""Flujo de revisión humana de resúmenes (DOMINIO PURO).

Modela el ciclo de revisión sobre un SummaryResult: aprobar / rechazar /
editar, con estado, revisor y nota. No hace IO ni ejecuta modelos; la
persistencia y la API viven en adaptadores.

Regla clave: no se puede APROBAR un resultado que falla QA gates de severidad
'error', salvo forzado explícito (queda registrado).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .contract import SummaryResult
from .qa import check_result

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EDITED = "edited"


@dataclass
class ReviewRecord:
    doc_id: str
    state: str = PENDING
    reviewer: str = ""
    note: str = ""
    history: list[dict] = field(default_factory=list)

    def _log(self, action: str, reviewer: str, note: str) -> None:
        self.history.append({"action": action, "reviewer": reviewer,
                             "note": note})

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id, "state": self.state,
            "reviewer": self.reviewer, "note": self.note,
            "history": self.history,
        }


class ReviewError(Exception):
    """Acción de revisión no permitida (p. ej. aprobar con errores QA)."""


def reject(record: ReviewRecord, reviewer: str, note: str = "") -> ReviewRecord:
    record.state = REJECTED
    record.reviewer = reviewer
    record.note = note
    record._log(REJECTED, reviewer, note)
    return record


def approve(
    record: ReviewRecord,
    result: SummaryResult,
    reviewer: str,
    *,
    note: str = "",
    force: bool = False,
) -> ReviewRecord:
    """Aprueba si no hay fallos QA de severidad 'error' (o si force=True)."""
    rep = check_result(result)
    errors = [f for f in rep.failures if f.severity == "error"]
    if errors and not force:
        raise ReviewError(
            f"no se puede aprobar: {len(errors)} fallo(s) QA de error "
            f"({', '.join(f.gate for f in errors)}). Usa force para forzar."
        )
    record.state = APPROVED
    record.reviewer = reviewer
    if errors and force:
        note = (note + f" [FORZADO pese a: "
                f"{', '.join(f.gate for f in errors)}]").strip()
    record.note = note
    record._log(APPROVED, reviewer, note)
    return record


def edit_sections(
    result: SummaryResult,
    record: ReviewRecord,
    changes: dict[str, str],
    reviewer: str,
    *,
    note: str = "",
) -> tuple[SummaryResult, ReviewRecord]:
    """Aplica cambios a secciones concretas, preservando el resto.

    Devuelve el resultado editado y el record en estado 'edited'.
    """
    for key, value in changes.items():
        result.secciones[key] = value
    result.meta["edited_by"] = reviewer
    record.state = EDITED
    record.reviewer = reviewer
    record.note = note
    record._log(EDITED, reviewer, f"{note} (secciones: {sorted(changes)})")
    return result, record
