"""Política compartida de extracción, revisión y fallback determinista."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

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
    completion: dict = field(default_factory=dict)

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
            "completion_checked": False,
            "completion_succeeded": False,
            "completion_retry_attempted": False,
            "completion_retry_succeeded": False,
            "completion_retry_error_type": "",
            "completion_retry_failure_phase": "",
            "missing_abstract_evidence": [],
            **self.completion,
        }


def _extract_window(
    text: str,
    llm: TextLLM | None,
    context_chars: int = ABSTRACT_REFINE_CONTEXT_CHARS,
    *,
    event_sink: Callable[..., None] | None = None,
    debug_sink: Callable[..., None] | None = None,
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

    completion = {}
    try:
        abstracts = refine_abstracts(
            text,
            candidates,
            llm,
            context_chars,
            event_sink=emit,
            diagnostics=completion,
            debug_sink=debug_sink,
        )
    except Exception as exc:  # noqa: BLE001 — el fallo de revisión no invalida el documento
        retained = [a for a in candidates if not suspicious_candidate(a.text)]
        return AbstractExtractionResult(
            retained, count, True, False, exc, phase, count - len(retained)
        )
    return AbstractExtractionResult(abstracts, count, True, True, completion=completion)


def extract_refined_abstracts(
    text: str,
    llm: TextLLM | None,
    context_chars: int = ABSTRACT_REFINE_CONTEXT_CHARS,
    *,
    event_sink: Callable[..., None] | None = None,
    debug_sink: Callable[..., None] | None = None,
) -> AbstractExtractionResult:
    """Revisa la ventana inicial y los encabezados fuera de ella."""
    from .abstracts import _find_abstract_headers

    headers = _find_abstract_headers(text)
    if type(context_chars) is not int or context_chars <= 0:
        return _extract_window(
            text, llm, context_chars, event_sink=event_sink, debug_sink=debug_sink
        )

    def window_end(start: int) -> int:
        end = min(len(text), start + context_chars)
        crossing = [h.start() for h in headers if start < h.start() < end]
        if end < len(text) and crossing:
            # Revisa completo en la próxima ventana el último encabezado cercano al corte.
            last = crossing[-1]
            candidates = extract_abstracts(text[last:])
            if (
                candidates
                and last + len(candidates[0].text) + len(candidates[0].header) > end
            ):
                end = last
        return end

    attempts = 0
    offset = 0

    def debug(**fields):
        nonlocal attempts
        number = offset + fields["attempt"]
        attempts = max(attempts, number)
        if debug_sink is not None:
            debug_sink(**{**fields, "attempt": number})

    end = window_end(0)
    result = _extract_window(
        text,
        llm,
        end or context_chars,
        event_sink=event_sink,
        debug_sink=debug if debug_sink is not None else None,
    )
    if llm is None or result.error is not None:
        return result
    covered = end
    windows = []
    for header in headers:
        if header.start() < covered:
            continue
        start = header.start()
        end = window_end(start)
        offset = attempts
        extra = _extract_window(
            text[start:end],
            llm,
            context_chars,
            event_sink=event_sink,
            debug_sink=debug if debug_sink is not None else None,
        )
        result.abstracts.extend(extra.abstracts)
        result.discarded_candidates += extra.discarded_candidates
        windows.append({"start": start, "end": end, **extra.diagnostics()})
        if extra.error is not None:
            result.error, result.failure_phase = extra.error, extra.failure_phase
            result.refinement_succeeded = False
        covered = end
    if windows:
        result.completion["windows"] = windows
    return result
