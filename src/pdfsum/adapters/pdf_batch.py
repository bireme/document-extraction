"""Flujo end-to-end desde PDFs (adaptador de aplicación).

Arranca desde la fuente real (PDFs), transcribe (puerto Transcriber) con caché
en ocr/, resume (puerto Summarizer) con QA gates, y escribe summaries/ +
report.json en el Workspace. La transcripción es idempotente: si ya existe
ocr/<doc_id>.txt, se reutiliza sin re-invocar al transcriber.
"""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from ..contract import Summarizer, Transcriber
from ..metrics import BatchItem, batch_metrics
from ..pipeline import summarize_document
from ..qa import check_result
from ..workspace import Workspace
from .observability import (
    EventLog,
    InfrastructureMonitor,
    atomic_write_json,
    utc_now,
)


def transcribe_pdfs(
    in_dir: str,
    workspace: Workspace,
    transcriber: Transcriber,
    *,
    pattern: str = "*.pdf",
) -> dict[str, dict]:
    """Transcribe todos los PDFs a ocr/<doc_id>.txt (cacheado). Devuelve meta.

    Si ocr/<doc_id>.txt ya existe, se reutiliza (no se re-transcribe).
    """
    workspace.ocr_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, dict] = {}
    for pdf in sorted(Path(in_dir).glob(pattern)):
        doc_id = pdf.stem
        ocr_file = workspace.ocr_path(doc_id)
        started = time.perf_counter()
        if ocr_file.exists():
            text = ocr_file.read_text(encoding="utf-8", errors="replace")
            meta[doc_id] = {
                "pages": text.count("=== pág") or 1,
                "source_kind": "cached",
                "cached": True,
                "transcription_seconds": time.perf_counter() - started,
            }
            continue
        tr = transcriber.transcribe(str(pdf))
        ocr_file.write_text(tr.text, encoding="utf-8")
        meta[doc_id] = {
            "pages": tr.pages,
            "source_kind": tr.source_kind.value,
            "cached": False,
            "transcription_seconds": time.perf_counter() - started,
        }
    return meta


def run_batch_pdfs(
    in_dir: str,
    workspace: Workspace,
    transcriber: Transcriber,
    summarizer: Summarizer,
    *,
    long_strategy: str = "excerpt",
) -> dict:
    """Flujo completo con eventos y checkpoints durables por documento."""
    workspace.summaries_dir.mkdir(parents=True, exist_ok=True)
    workspace.ocr_dir.mkdir(parents=True, exist_ok=True)
    workspace.report_path.parent.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(Path(in_dir).glob("*.pdf"))
    run_id = str(uuid4())
    started_at = utc_now()
    log_dir = workspace.report_path.parent
    events = EventLog(log_dir / "events.jsonl", run_id)
    monitor = InfrastructureMonitor(
        log_dir / "infrastructure.jsonl", workspace.root, run_id=run_id
    )
    items: list[BatchItem] = []
    documents: list[dict] = []
    status = "running"

    def make_report() -> dict:
        failed = sum(doc["status"] == "failed" for doc in documents)
        completed = sum(doc["status"] == "completed" for doc in documents)
        generated_at = utc_now()
        return {
            "report_version": "3.0",
            "run_id": run_id,
            "status": status,
            "started_at": started_at,
            "updated_at": generated_at,
            "generated_at": generated_at,
            "duration_unit": "seconds",
            "progress": {
                "discovered": len(pdfs),
                "processed": len(documents),
                "completed": completed,
                "failed": failed,
                "remaining": max(0, len(pdfs) - len(documents)),
            },
            "metrics": batch_metrics(items).to_dict(),
            "infrastructure": monitor.summary(),
            "documents": documents,
        }

    def checkpoint() -> dict:
        current = make_report()
        atomic_write_json(workspace.report_path, current)
        return current

    monitor.start()
    events.write("run_started", documents_discovered=len(pdfs), input=str(in_dir))
    checkpoint()
    try:
        for pdf in pdfs:
            doc_id = pdf.stem
            phases: dict[str, float] = {}
            document_started = time.perf_counter()
            monitor.set_context(doc_id=doc_id, phase="transcripcion")
            events.write("document_started", doc_id=doc_id)
            try:
                started = time.perf_counter()
                ocr_file = workspace.ocr_path(doc_id)
                if ocr_file.exists():
                    text = ocr_file.read_text(encoding="utf-8", errors="replace")
                    om = {
                        "pages": text.count("=== pág") or 1,
                        "source_kind": "cached",
                        "cached": True,
                    }
                else:
                    set_event_sink = getattr(transcriber, "set_event_sink", None)
                    previous_sink = None
                    if callable(set_event_sink):
                        previous_sink = set_event_sink(events.write)
                    try:
                        tr = transcriber.transcribe(str(pdf))
                    finally:
                        if callable(set_event_sink):
                            set_event_sink(previous_sink)
                    ocr_file.write_text(tr.text, encoding="utf-8")
                    om = {
                        "pages": tr.pages,
                        "source_kind": tr.source_kind.value,
                        "cached": False,
                    }
                phases["transcripcion"] = time.perf_counter() - started
                events.write(
                    "phase_completed",
                    doc_id=doc_id,
                    phase="transcripcion",
                    seconds=round(phases["transcripcion"], 6),
                    cached=om["cached"],
                )

                started = time.perf_counter()
                monitor.set_context(doc_id=doc_id, phase="lectura_ocr")
                text = ocr_file.read_text(encoding="utf-8", errors="replace")
                phases["lectura_ocr"] = time.perf_counter() - started
                started = time.perf_counter()
                monitor.set_context(doc_id=doc_id, phase="resumen")
                res = summarize_document(
                    doc_id=doc_id,
                    text=text,
                    summarizer=summarizer,
                    pages=om["pages"],
                    long_strategy=long_strategy,
                )
                phases["resumen"] = time.perf_counter() - started
                events.write(
                    "phase_completed",
                    doc_id=doc_id,
                    phase="resumen",
                    seconds=round(phases["resumen"], 6),
                )
                res.meta["source_kind"] = om["source_kind"]
                started = time.perf_counter()
                monitor.set_context(doc_id=doc_id, phase="qa")
                qa = check_result(res)
                phases["qa"] = time.perf_counter() - started
                record = res.to_dict()
                record["_qa"] = qa.to_dict()
                started = time.perf_counter()
                monitor.set_context(doc_id=doc_id, phase="escritura_resultado")
                atomic_write_json(workspace.summary_path(doc_id), record)
                phases["escritura_resultado"] = time.perf_counter() - started
                item = BatchItem(
                    result=res,
                    qa=qa,
                    seconds=sum(phases.values()),
                    phase_seconds=phases,
                )
                items.append(item)
                documents.append(
                    {
                        "doc_id": doc_id,
                        "status": "completed",
                        "tipo": res.tipo_documento,
                        "idioma": res.idioma_principal,
                        "qa_ok": qa.is_ok,
                        "source_kind": om["source_kind"],
                        "transcription_cached": om["cached"],
                        "gates": [failure.gate for failure in qa.failures],
                        "tiempo_total": round(item.seconds, 3),
                        "tiempos_por_fase": {
                            phase: round(seconds, 6)
                            for phase, seconds in phases.items()
                        },
                    }
                )
                events.write(
                    "document_completed",
                    doc_id=doc_id,
                    seconds=round(time.perf_counter() - document_started, 3),
                    qa_ok=qa.is_ok,
                )
            except Exception as exc:  # noqa: BLE001 - aislar el fallo por documento
                error = f"{type(exc).__name__}: {exc}"[:2000]
                documents.append(
                    {
                        "doc_id": doc_id,
                        "status": "failed",
                        "error": error,
                        "tiempo_total": round(
                            time.perf_counter() - document_started, 3
                        ),
                        "tiempos_por_fase": {
                            phase: round(seconds, 6)
                            for phase, seconds in phases.items()
                        },
                    }
                )
                events.write("document_failed", doc_id=doc_id, error=error)
            monitor.set_context()
            checkpoint()
        status = (
            "completed_with_errors"
            if any(doc["status"] == "failed" for doc in documents)
            else "completed"
        )
        checkpoint()
        events.write("run_completed", status=status)
    except BaseException as exc:
        status = "interrupted"
        events.write("run_interrupted", error=type(exc).__name__)
        checkpoint()
        raise
    finally:
        monitor.stop()
        report = checkpoint()
    return report
