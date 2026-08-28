"""Runner de lote (capa de aplicación/adaptador): orquesta el procesamiento.

Une el pipeline de dominio (summarize_document) con la cola (idempotencia/
reintentos), los QA gates y las métricas. Escribe un .json por documento y un
report.json de lote. Hace IO (archivos), por eso vive fuera del dominio puro.
"""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from ..contract import Summarizer, SummaryResult
from ..metrics import BatchItem, batch_metrics
from ..pipeline import summarize_document
from ..qa import check_result
from ..queue import JobQueue
from .job_store import FileJobStore
from .observability import (
    EventLog,
    InfrastructureMonitor,
    atomic_write_json,
    utc_now,
)


def run_batch(
    in_dir: str,
    out_dir: str,
    summarizer: Summarizer,
    *,
    pattern: str = "*.txt",
    max_retries: int = 2,
) -> dict:
    """Procesa todos los .txt de in_dir; escribe resúmenes + report.json.

    Devuelve el dict de métricas del lote. Idempotente: re-ejecutar no
    reprocesa documentos ya completados (estado en out_dir/_jobs.json).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    store = FileJobStore(str(out / "_jobs.json"))
    queue = JobQueue(store, max_retries=max_retries)

    inputs = sorted(Path(in_dir).glob(pattern))
    run_id = str(uuid4())
    started_at = utc_now()
    events = EventLog(out / "events.jsonl", run_id)
    monitor = InfrastructureMonitor(out / "infrastructure.jsonl", out)
    items: list[BatchItem] = []
    documents: list[dict] = []
    status = "running"

    def make_report() -> dict:
        completed = sum(doc["status"] == "completed" for doc in documents)
        failed = sum(doc["status"] == "failed" for doc in documents)
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
                "discovered": len(inputs),
                "processed": len(documents),
                "completed": completed,
                "failed": failed,
                "remaining": max(0, len(inputs) - len(documents)),
            },
            "metrics": batch_metrics(items).to_dict(),
            "infrastructure": monitor.summary(),
            "queue": queue.counts(),
            "documents": documents,
        }

    def checkpoint() -> dict:
        current = make_report()
        atomic_write_json(out / "report.json", current)
        return current

    monitor.start()
    events.write("run_started", documents_discovered=len(inputs), input=str(in_dir))
    checkpoint()
    try:
        for txt in inputs:
            doc_id = txt.stem
            phases: dict[str, float] = {}
            document_started = time.perf_counter()
            events.write("document_started", doc_id=doc_id)
            try:
                t0 = time.perf_counter()
                payload = txt.read_text(encoding="utf-8", errors="replace")
                phases["lectura_texto"] = time.perf_counter() - t0
                summary_seconds = 0.0
                summary_executed = False

                def work(did: str, text: str) -> dict:
                    nonlocal summary_executed, summary_seconds
                    summary_executed = True
                    started = time.perf_counter()
                    res = summarize_document(
                        doc_id=did, text=text, summarizer=summarizer
                    )
                    summary_seconds += time.perf_counter() - started
                    return res.to_dict()

                t0 = time.perf_counter()
                job = queue.submit(doc_id, payload, work)
                queue_seconds = time.perf_counter() - t0
                phases["resumen"] = summary_seconds
                phases["cola"] = max(0.0, queue_seconds - summary_seconds)

                if job.result is None:
                    documents.append(
                        {
                            "doc_id": doc_id,
                            "status": "failed",
                            "attempts": job.attempts,
                            "error": job.error[:2000],
                            "tiempo_total": round(
                                time.perf_counter() - document_started, 3
                            ),
                            "tiempos_por_fase": {
                                phase: round(seconds, 6)
                                for phase, seconds in phases.items()
                            },
                        }
                    )
                    events.write(
                        "document_failed",
                        doc_id=doc_id,
                        attempts=job.attempts,
                        error=job.error[:2000],
                    )
                    checkpoint()
                    continue

                res = SummaryResult.from_dict(job.result)
                t0 = time.perf_counter()
                qa = check_result(res)
                phases["qa"] = time.perf_counter() - t0
                record = res.to_dict()
                record["_qa"] = qa.to_dict()
                t0 = time.perf_counter()
                atomic_write_json(out / f"{doc_id}.json", record)
                phases["escritura_resultado"] = time.perf_counter() - t0
                item = BatchItem(
                    result=res,
                    qa=qa,
                    seconds=sum(phases.values()),
                    phase_seconds=phases,
                    cache_hit=not summary_executed,
                )
                items.append(item)
                documents.append(
                    {
                        "doc_id": doc_id,
                        "status": "completed",
                        "tipo": res.tipo_documento,
                        "idioma": res.idioma_principal,
                        "qa_ok": qa.is_ok,
                        "gates": [failure.gate for failure in qa.failures],
                        "cache_hit": item.cache_hit,
                        "attempts": job.attempts,
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
                    cache_hit=item.cache_hit,
                )
            except Exception as exc:  # noqa: BLE001 - isolar falha por documento
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
            checkpoint()
        status = "completed_with_errors" if any(
            doc["status"] == "failed" for doc in documents
        ) else "completed"
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
