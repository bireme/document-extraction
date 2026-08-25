"""Runner de lote (capa de aplicación/adaptador): orquesta el procesamiento.

Une el pipeline de dominio (summarize_document) con la cola (idempotencia/
reintentos), los QA gates y las métricas. Escribe un .json por documento y un
report.json de lote. Hace IO (archivos), por eso vive fuera del dominio puro.
"""

from __future__ import annotations

import json
import time
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
        payload = txt.read_text(encoding="utf-8", errors="replace")

        def work(did: str, text: str) -> dict:
            res = summarize_document(doc_id=did, text=text, summarizer=summarizer)
            return res.to_dict()

        t0 = time.time()
        job = queue.submit(doc_id, payload, work)
        elapsed = time.time() - t0

        if job.result is None:
            continue  # falló todos los reintentos; queda en la cola como failed
        res = SummaryResult.from_dict(job.result)
        qa = check_result(res)
        # escribir resumen + su QA
        record = res.to_dict()
        record["_qa"] = qa.to_dict()
        (out / f"{doc_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        items.append(BatchItem(result=res, qa=qa, seconds=elapsed))

    metrics = batch_metrics(items)
    report = {
        "metrics": metrics.to_dict(),
        "queue": queue.counts(),
        "documents": [
            {
                "doc_id": it.result.doc_id,
                "tipo": it.result.tipo_documento,
                "idioma": it.result.idioma_principal,
                "qa_ok": it.qa.is_ok,
                "gates": [f.gate for f in it.qa.failures],
            }
            for it in items
        ],
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
