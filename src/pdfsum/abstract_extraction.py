"""Política compartida de extracción, revisión y fallback determinista."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .abstract_refine import ABSTRACT_REFINE_CONTEXT_CHARS, refine_abstracts
from .abstracts import extract_abstracts, suspicious_candidate
from .contract import Abstract, TextLLM


@dataclass
class AbstractExtractionResult:
    """Resultado y diagnóstico interno, sin decidir su presentación externa."""

    abstracts: list[Abstract]
    candidate_count: int
    refinement_attempted: bool
    refinement_succeeded: bool
    error: Exception | None = None
    failure_phase: str = ""
    discarded_candidates: int = 0

    def diagnostics(self) -> dict:
        """Separa el éxito operativo del respaldo de los resúmenes extraídos."""
        return {
            "refinement_attempted": self.refinement_attempted,
            "refinement_succeeded": self.refinement_succeeded,
            "fallback": self.error is not None,
            "fallback_reason": str(self.error) if self.error else "",
            "failure_phase": self.failure_phase,
            "error_type": type(self.error).__name__ if self.error else "",
            "candidate_count": self.candidate_count,
            "final_count": len(self.abstracts),
            "discarded_candidates": self.discarded_candidates,
        }


def extract_refined_abstracts(
    text: str,
    llm: TextLLM | None,
    context_chars: int = ABSTRACT_REFINE_CONTEXT_CHARS,
    *,
    event_sink: Callable[..., None] | None = None,
) -> AbstractExtractionResult:
    """Revisa incluso sin candidatos; el fallback excluye contaminación evidente."""
    candidates = extract_abstracts(text)
    count = len(candidates)
    if llm is None:
        return AbstractExtractionResult(candidates, count, False, False)
    if event_sink is not None:
        event_sink("phase_started", phase="preparacion_revision", candidate_count=count)
    phase = "preparacion_revision"

    def emit(event: str, **fields) -> None:
        nonlocal phase
        if event == "phase_started":
            phase = fields["phase"]
        if event_sink is not None:
            event_sink(event, **fields)

    try:
        abstracts = refine_abstracts(
            text, candidates, llm, context_chars, event_sink=emit
        )
    except Exception as exc:  # noqa: BLE001 — el fallo de revisión no invalida el documento
        retained = [a for a in candidates if not suspicious_candidate(a.text)]
        return AbstractExtractionResult(
            retained, count, True, False, exc, phase, count - len(retained)
        )
    return AbstractExtractionResult(abstracts, count, True, True)
