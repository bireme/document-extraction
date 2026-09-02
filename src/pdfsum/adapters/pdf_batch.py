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
from ..transcript_qa import check_transcript
from ..workspace import Workspace
from .observability import (
    EventLog,
    InfrastructureMonitor,
    atomic_write_json,
    utc_now,
)
from .ocr_meta import (
    build_legacy_meta,
    build_meta,
    cache_valid,
    read_meta,
    sha256_file,
    write_meta,
)


def _load_or_transcribe(
    pdf: Path,
    workspace: Workspace,
    transcriber: Transcriber,
    *,
    retranscribe: bool = False,
) -> tuple[str, dict, dict]:
    """Texto + info de operación + meta persistida, con caché versionada.

    Reutiliza ocr/<doc_id>.txt SOLO si su meta.json tiene el mismo sha256
    del PDF y la misma ocr_pipeline_version. Caché LEGACY (txt sin meta):
    se reutiliza si el PDF no cambió, generando meta {'legacy': true}
    (nunca re-OCR masivo silencioso). `retranscribe=True` fuerza re-OCR.
    """
    doc_id = pdf.stem
    ocr_file = workspace.ocr_path(doc_id)
    if ocr_file.exists() and not retranscribe:
        meta = read_meta(ocr_file)
        if cache_valid(meta, pdf):
            text = ocr_file.read_text(encoding="utf-8", errors="replace")
            return (
                text,
                {"pages": meta["pages"], "source_kind": "cached", "cached": True},
                meta,
            )
        if meta is None:
            # caché previa a FASE16: reutilizar con marca legacy
            text = ocr_file.read_text(encoding="utf-8", errors="replace")
            meta = build_legacy_meta(doc_id, pdf, text)
            write_meta(ocr_file, meta)
            return (
                text,
                {"pages": meta["pages"], "source_kind": "cached", "cached": True},
                meta,
            )
        if meta.get("legacy") and meta.get("pdf_sha256") == sha256_file(pdf):
            text = ocr_file.read_text(encoding="utf-8", errors="replace")
            return (
                text,
                {"pages": meta["pages"], "source_kind": "cached", "cached": True},
                meta,
            )
        # meta inválida (PDF cambiado o pipeline nuevo): re-transcribir
    tr = transcriber.transcribe(str(pdf))
    ocr_file.write_text(tr.text, encoding="utf-8")
    meta = build_meta(doc_id, pdf, tr, getattr(transcriber, "lang", ""))
    write_meta(ocr_file, meta)
    return (
        tr.text,
        {"pages": tr.pages, "source_kind": tr.source_kind.value, "cached": False},
        meta,
    )


def transcribe_pdfs(
    in_dir: str,
    workspace: Workspace,
    transcriber: Transcriber,
    *,
    pattern: str = "*.pdf",
    retranscribe: bool = False,
) -> dict[str, dict]:
    """Transcribe todos los PDFs a ocr/<doc_id>.txt (+ meta.json, cacheado)."""
    workspace.ocr_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, dict] = {}
    for pdf in sorted(Path(in_dir).glob(pattern)):
        started = time.perf_counter()
        _, om, _ = _load_or_transcribe(
            pdf, workspace, transcriber, retranscribe=retranscribe
        )
        om["transcription_seconds"] = time.perf_counter() - started
        meta[pdf.stem] = om
    return meta


def run_batch_pdfs(
    in_dir: str,
    workspace: Workspace,
    transcriber: Transcriber,
    summarizer: Summarizer,
    *,
    long_strategy: str = "excerpt",
    retranscribe: bool = False,
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

    def transcription_quality_summary() -> dict:
        """Agregado FASE16 de calidad de transcripción del lote (aditivo)."""
        docs = [d for d in documents if "transcription_quality" in d]
        confs = [
            d["transcription_quality"]["conf_media"]
            for d in docs
            if d["transcription_quality"].get("conf_media") is not None
        ]
        return {
            "docs_evaluados": len(docs),
            "docs_con_error": sum(
                1 for d in docs if not d["transcription_quality"]["passed"]
            ),
            "docs_con_warnings": sum(
                1 for d in docs if d["transcription_quality"]["gates"]
            ),
            "docs_legacy": sum(
                1 for d in docs if d["transcription_quality"].get("legacy")
            ),
            "paginas_vlm": sum(
                d["transcription_quality"].get("paginas_vlm", 0) for d in docs
            ),
            "paginas_vacias": sum(
                d["transcription_quality"].get("paginas_vacias", 0) for d in docs
            ),
            "conf_media": round(sum(confs) / len(confs), 2) if confs else None,
        }

    def make_report() -> dict:
        failed = sum(doc["status"] == "failed" for doc in documents)
        completed = sum(doc["status"] == "completed" for doc in documents)
        generated_at = utc_now()
        return {
            "report_version": "3.1",
            "transcription_quality": transcription_quality_summary(),
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
                set_event_sink = getattr(transcriber, "set_event_sink", None)
                previous_sink = None
                if callable(set_event_sink):
                    previous_sink = set_event_sink(events.write)
                try:
                    text, om, ocr_meta = _load_or_transcribe(
                        pdf, workspace, transcriber, retranscribe=retranscribe
                    )
                finally:
                    if callable(set_event_sink):
                        set_event_sink(previous_sink)
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

                # FASE16: QA del transcript ANTES de resumir (no bloqueante).
                started = time.perf_counter()
                monitor.set_context(doc_id=doc_id, phase="qa_transcripcion")
                tqa = check_transcript(text, ocr_meta, doc_id=doc_id)
                phases["qa_transcripcion"] = time.perf_counter() - started
                events.write(
                    "transcript_qa_completed",
                    doc_id=doc_id,
                    passed=tqa.is_ok,
                    gates=[f.gate for f in tqa.failures],
                )

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
                record["_qa"]["transcript"] = tqa.to_dict()
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
                        "transcription_quality": {
                            "passed": tqa.is_ok,
                            "gates": [f.gate for f in tqa.failures],
                            "legacy": bool(ocr_meta.get("legacy")),
                            "conf_media": (ocr_meta.get("quality") or {}).get(
                                "conf_media"
                            ),
                            "paginas_vlm": (ocr_meta.get("quality") or {}).get(
                                "paginas_vlm", 0
                            ),
                            "paginas_vacias": (ocr_meta.get("quality") or {}).get(
                                "paginas_vacias", 0
                            ),
                        },
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
