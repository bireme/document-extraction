"""Extracción por lote de resúmenes presentes en los documentos."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from ..abstract_extraction import extract_refined_abstracts
from ..abstract_refine import ABSTRACT_REFINE_CONTEXT_CHARS
from ..contract import TextLLM, Transcriber
from ..workspace import Workspace
from .abstract_refine_debug import AbstractRefineDebugSink
from .observability import EventLog, atomic_write_json


def extract_abstracts_from_pdfs(
    in_dir: str,
    workspace: Workspace,
    transcriber: Transcriber,
    llm: TextLLM,
    context_chars: int = ABSTRACT_REFINE_CONTEXT_CHARS,
    *,
    backend: str | None = None,
    model: str | None = None,
    abstract_refine_debug_dir: str | Path | None = None,
    format_error: Callable[[BaseException], str] = str,
) -> dict:
    """Transcribe y extrae con eventos y checkpoints del ejecutor de lotes."""
    workspace.ocr_dir.mkdir(parents=True, exist_ok=True)
    workspace.abstracts_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid4())
    events = EventLog(workspace.report_path.parent / "events.jsonl", run_id)
    logger = logging.getLogger(__name__)
    backend = (
        backend
        or getattr(llm, "provider", None)
        or {
            "OllamaSummarizer": "ollama",
            "AnthropicSummarizer": "anthropic",
            "FakeSummarizer": "fake",
        }.get(type(llm).__name__, type(llm).__name__)
    )
    model = model or getattr(llm, "model", None)
    documentos = []
    metrics = {"revision_llm_exitosa": 0, "fallback_determinista": 0, "sin_abstract": 0}

    def checkpoint() -> dict:
        encontrados = sum(d["status"] == "found" for d in documentos)
        report = {
            "total": len(documentos),
            "found": encontrados,
            "not_found": len(documentos) - encontrados,
            "documents": documentos,
            "metrics": dict(metrics),
        }
        # El reporte operativo no duplica el contenido de los documentos.
        atomic_write_json(
            workspace.report_path,
            {
                **report,
                "documents": [
                    {k: v for k, v in d.items() if k != "abstracts"} for d in documentos
                ],
                "run_id": run_id,
                "command": "extract-abstracts",
            },
        )
        return report

    pdfs = sorted(Path(in_dir).glob("*.pdf"))
    events.write(
        "run_started", command="extract-abstracts", documents_discovered=len(pdfs)
    )
    checkpoint()
    for pdf in pdfs:
        doc_id = pdf.stem
        document_started = time.perf_counter()
        phase = "transcripcion"
        phase_started = document_started
        details = {}

        def emit(event: str, *, doc_id=doc_id, **fields) -> None:
            events.write(event, doc_id=doc_id, **fields)
            logger.info(
                "Evento de extracción de resúmenes: %s (%s)",
                event,
                doc_id,
                extra={"event": event, "run_id": run_id, "doc_id": doc_id, **fields},
            )

        def next_phase(event: str, *, details=details, emit=emit, **fields) -> None:
            nonlocal phase, phase_started, review_started
            if event != "phase_started":
                emit(event, **fields)
                return
            emit(
                "phase_completed",
                phase=phase,
                seconds=round(time.perf_counter() - phase_started, 6),
            )
            phase = fields.pop("phase")
            phase_started = time.perf_counter()
            details.update(fields)
            emit(event, phase=phase, **details)
            if phase == "preparacion_revision":
                review_started = time.perf_counter()
                emit("abstract_refine_started", **details)

        emit("document_started")
        emit("phase_started", phase=phase)
        try:
            ocr_file = workspace.ocr_path(doc_id)
            if ocr_file.exists():
                text = ocr_file.read_text(encoding="utf-8", errors="replace")
                source_kind = "cached"
            else:
                set_sink = getattr(transcriber, "set_event_sink", None)
                previous = set_sink(events.write) if callable(set_sink) else None
                try:
                    tr = transcriber.transcribe(str(pdf))
                finally:
                    if callable(set_sink):
                        set_sink(previous)
                text = tr.text
                source_kind = tr.source_kind.value
                ocr_file.write_text(text, encoding="utf-8")
            next_phase(
                "phase_started",
                phase="extraccion_determinista",
                source_kind=source_kind,
            )
            details.update(backend=backend, model=model)
            review_started = time.perf_counter()
            extraction = extract_refined_abstracts(
                text,
                llm,
                context_chars,
                event_sink=next_phase,
                debug_sink=(
                    AbstractRefineDebugSink(Path(abstract_refine_debug_dir), doc_id)
                    if abstract_refine_debug_dir is not None
                    else None
                ),
            )
            abstracts = extraction.abstracts
            details["discarded_candidates"] = extraction.discarded_candidates
            details.update(extraction.completion)
            fallback = False
            error = {}
            if extraction.error is not None:
                exc = extraction.error
                fallback = True
                error = {
                    "error_type": type(exc).__name__,
                    "error": format_error(exc),
                    "failure_phase": phase,
                }
                emit("abstract_refine_fallback", **details, **error, fallback=True)
                logger.warning(
                    "Revisión de resúmenes fallida; se aplica fallback conservador: "
                    "%s (%s: %s), etapa=%s",
                    doc_id,
                    type(exc).__name__,
                    format_error(exc),
                    phase,
                    extra={
                        "doc_id": doc_id,
                        "run_id": run_id,
                        "event": "abstract_refine_fallback",
                        **error,
                    },
                )
            emit(
                "phase_failed" if fallback else "phase_completed",
                phase=phase,
                seconds=round(time.perf_counter() - phase_started, 6),
                **error,
            )
            emit(
                "abstract_refine_completed",
                **details,
                **error,
                seconds=round(time.perf_counter() - review_started, 6),
                accepted_count=0 if fallback else len(abstracts),
                final_count=len(abstracts),
                fallback=fallback,
            )
            phase = "escritura_resultado"
            resultado = {
                "doc_id": doc_id,
                "status": "found" if abstracts else "not_found",
                "source_kind": source_kind,
                "abstracts": [
                    {
                        "lang": a.lang,
                        "header": a.header,
                        "text": a.text,
                        "keywords": a.keywords,
                    }
                    for a in abstracts
                ],
            }
            atomic_write_json(workspace.abstract_path(doc_id), resultado)
            documentos.append(
                {**resultado, "abstract_extraction": extraction.diagnostics()}
            )
            metrics[
                "fallback_determinista" if fallback else "revision_llm_exitosa"
            ] += 1
            metrics["sin_abstract"] += int(not abstracts)
            emit(
                "document_completed",
                seconds=round(time.perf_counter() - document_started, 6),
                status=resultado["status"],
                final_count=len(abstracts),
                fallback=fallback,
            )
            checkpoint()
        except BaseException as exc:
            emit(
                "document_failed",
                phase=phase,
                error_type=type(exc).__name__,
                error=format_error(exc),
            )
            events.write(
                "run_interrupted",
                error_type=type(exc).__name__,
                error=format_error(exc),
            )
            raise
    events.write("run_completed", status="completed", metrics=metrics)
    return checkpoint()
