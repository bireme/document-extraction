"""Runner de lote (capa de aplicación/adaptador): orquesta el procesamiento.

Une el pipeline de dominio (summarize_document) con la cola (idempotencia/
reintentos), los QA gates y las métricas. Escribe un .json por documento y un
report.json de lote. Hace IO (archivos), por eso vive fuera del dominio puro.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..contract import Summarizer, SummaryResult
from ..metrics import BatchItem, batch_metrics
from ..pipeline import summarize_document
from ..qa import check_result
from ..queue import JobQueue
from .job_store import FileJobStore


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

    items: list[BatchItem] = []
    for txt in sorted(Path(in_dir).glob(pattern)):
        doc_id = txt.stem
        phases: dict[str, float] = {}
        t0 = time.perf_counter()
        payload = txt.read_text(encoding="utf-8", errors="replace")
        phases["lectura_texto"] = time.perf_counter() - t0
        summary_seconds = 0.0
        summary_executed = False

        def work(did: str, text: str) -> dict:
            nonlocal summary_executed, summary_seconds
            summary_executed = True
            started = time.perf_counter()
            res = summarize_document(doc_id=did, text=text, summarizer=summarizer)
            summary_seconds += time.perf_counter() - started
            return res.to_dict()

        t0 = time.perf_counter()
        job = queue.submit(doc_id, payload, work)
        queue_seconds = time.perf_counter() - t0
        phases["resumen"] = summary_seconds
        phases["cola"] = max(0.0, queue_seconds - summary_seconds)

        if job.result is None:
            continue  # falló todos los reintentos; queda en la cola como failed
        res = SummaryResult.from_dict(job.result)
        t0 = time.perf_counter()
        qa = check_result(res)
        phases["qa"] = time.perf_counter() - t0
        # escribir resumen + su QA
        record = res.to_dict()
        record["_qa"] = qa.to_dict()
        t0 = time.perf_counter()
        (out / f"{doc_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        phases["escritura_resultado"] = time.perf_counter() - t0
        elapsed = sum(phases.values())
        items.append(
            BatchItem(
                result=res,
                qa=qa,
                seconds=elapsed,
                phase_seconds=phases,
                cache_hit=not summary_executed,
            )
        )

    metrics = batch_metrics(items)
    report = {
        "report_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_unit": "seconds",
        "metrics": metrics.to_dict(),
        "queue": queue.counts(),
        "documents": [
            {
                "doc_id": it.result.doc_id,
                "tipo": it.result.tipo_documento,
                "idioma": it.result.idioma_principal,
                "qa_ok": it.qa.is_ok,
                "gates": [f.gate for f in it.qa.failures],
                "cache_hit": it.cache_hit,
                "tiempo_total": round(it.seconds, 3),
                "tiempos_por_fase": {
                    phase: round(seconds, 6)
                    for phase, seconds in it.phase_seconds.items()
                },
            }
            for it in items
        ],
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
