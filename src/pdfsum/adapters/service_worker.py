"""Worker del servicio (adaptador de aplicación, FASE20).

Consume jobs persistidos en DirJobStore y ejecuta el flujo existente de
`run_batch_pdfs` para cada PDF subido, escribiendo artefactos idénticos a
`pdfsum run` (report 3.1, events.jsonl, meta OCR v4, summaries/*.json).

Diseño:
- La API encola jobs PENDING y guarda el PDF en inbox/<doc_id>/<doc_id>.pdf.
- El worker procesa jobs de a uno (run_once), usando un logs_dir por job:
  jobs/<job_id_saneado>/{report.json,events.jsonl,infrastructure.jsonl}
  y además actualiza summaries/report.json como 'último job' para la
  compatibilidad del endpoint /api/report.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from ..contract import Summarizer, Transcriber
from ..queue import FAILED, PENDING, JobQueue
from ..workspace import Workspace
from .job_store import DirJobStore
from .observability import atomic_write_json
from .pdf_batch import run_batch_pdfs


def _safe_job_dir(job_id: str) -> str:
    return job_id.replace(":", "@")


def run_once(
    workspace_root: str | Path,
    transcriber: Transcriber,
    summarizer: Summarizer,
    *,
    long_strategy: str = "excerpt",
    poll_states: set[str] | None = None,
    sleep_seconds: float = 0.0,
) -> int:
    """Procesa todos los jobs en estados `poll_states` (por defecto: pending).

    Devuelve el número de jobs procesados (intentados). Diseñado para tests.
    """
    root = Path(workspace_root)
    inbox = root / "inbox"
    store = DirJobStore(root / "service_jobs")
    queue = JobQueue(store)
    processed = 0
    states = poll_states or {PENDING, FAILED}

    for raw in store.all().values():
        if raw.get("state") not in states:
            continue
        doc_id = raw["doc_id"]
        job_id = raw["key"]
        pdf_dir = inbox / doc_id
        pdfs = list(pdf_dir.glob("*.pdf"))
        if not pdfs:
            continue

        def work(
            _doc_id: str,
            _payload: str,
            *,
            job_id: str = job_id,
            pdf_dir: Path = pdf_dir,
        ) -> dict:
            logs_dir = root / "jobs" / _safe_job_dir(job_id)
            ws = Workspace(root, logs_dir=logs_dir)
            report = run_batch_pdfs(
                str(pdf_dir),
                ws,
                transcriber,
                summarizer,
                retranscribe=False,
                long_strategy=long_strategy,
            )
            # compatibilidad: report "último job" en summaries/report.json
            atomic_write_json(root / "summaries" / "report.json", report)
            return report

        try:
            # payload idempotente: sha256 del PDF subido (contenido real).
            pdf_path = min(pdf_dir.glob("*.pdf"))
            payload = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            queue.submit(doc_id, payload, work)
            processed += 1
        except BaseException as exc:
            # Capturar incluso KeyboardInterrupt para preservar estado en disco.
            current = store.get(job_id) or raw
            current["state"] = FAILED
            current["error"] = f"{type(exc).__name__}: {exc}"
            store.put(job_id, current)
            raise

        if sleep_seconds:
            time.sleep(sleep_seconds)

    return processed


def main_loop(
    workspace_root: str | Path,
    transcriber: Transcriber,
    summarizer: Summarizer,
    *,
    long_strategy: str = "excerpt",
    interval_seconds: float = 1.0,
) -> None:
    """Loop infinito del worker (producción)."""
    while True:
        run_once(
            workspace_root,
            transcriber,
            summarizer,
            long_strategy=long_strategy,
        )
        time.sleep(interval_seconds)
