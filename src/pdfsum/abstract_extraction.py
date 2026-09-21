"""Política compartida de extracción, revisión y fallback determinista."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .abstract_refine import ABSTRACT_REFINE_CONTEXT_CHARS, refine_abstracts
from .abstracts import extract_abstracts
from .contract import Abstract, TextLLM


@dataclass
class AbstractExtractionResult:
    """Resultado y diagnóstico interno, sin decidir su presentación externa."""

    abstracts: list[Abstract]
    candidate_count: int
    refinement_attempted: bool
    refinement_succeeded: bool
    error: Exception | None = None


def extract_refined_abstracts(
    text: str,
    llm: TextLLM | None,
    context_chars: int = ABSTRACT_REFINE_CONTEXT_CHARS,
    *,
    event_sink: Callable[..., None] | None = None,
) -> AbstractExtractionResult:
    """Revisa incluso sin candidatos y conserva la extracción si falla el LLM."""
    candidates = extract_abstracts(text)
    count = len(candidates)
    if llm is None or count == 0:
        return AbstractExtractionResult(candidates, count, False, False)
    if event_sink is not None:
        event_sink("phase_started", phase="preparacion_revision", candidate_count=count)
    try:
        abstracts = refine_abstracts(
            text, candidates, llm, context_chars, event_sink=event_sink
        )
    except Exception as exc:  # noqa: BLE001 — el fallo de revisión no invalida el documento
        return AbstractExtractionResult(candidates, count, True, False, exc)
    return AbstractExtractionResult(abstracts, count, True, True)
