"""Flujo end-to-end desde PDFs (adaptador de aplicación).

Arranca desde la fuente real (PDFs), transcribe (puerto Transcriber) con caché
en ocr/, resume (puerto Summarizer) con QA gates, y escribe summaries/ +
report.json en el Workspace. La transcripción es idempotente: si ya existe
ocr/<doc_id>.txt, se reutiliza sin re-invocar al transcriber.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..contract import Summarizer, Transcriber
from ..metrics import BatchItem, batch_metrics
from ..pipeline import summarize_document
from ..qa import check_result
from ..workspace import Workspace


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
        if ocr_file.exists():
            text = ocr_file.read_text(encoding="utf-8", errors="replace")
            meta[doc_id] = {
                "pages": text.count("=== pág") or 1,
                "source_kind": "cached",
                "cached": True,
            }
            continue
        tr = transcriber.transcribe(str(pdf))
        ocr_file.write_text(tr.text, encoding="utf-8")
        meta[doc_id] = {
            "pages": tr.pages,
            "source_kind": tr.source_kind.value,
            "cached": False,
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
    """Flujo completo desde PDFs: transcribe (cache) -> resume -> report."""
    ocr_meta = transcribe_pdfs(in_dir, workspace, transcriber)
    workspace.summaries_dir.mkdir(parents=True, exist_ok=True)

    items: list[BatchItem] = []
    origen: dict[str, str] = {}
    for doc_id, om in ocr_meta.items():
        text = workspace.ocr_path(doc_id).read_text(encoding="utf-8", errors="replace")
        t0 = time.time()
        res = summarize_document(
            doc_id=doc_id,
            text=text,
            summarizer=summarizer,
            pages=om.get("pages", 1),
            long_strategy=long_strategy,
        )
        elapsed = time.time() - t0
        res.meta["source_kind"] = om.get("source_kind")
        qa = check_result(res)
        record = res.to_dict()
        record["_qa"] = qa.to_dict()
        workspace.summary_path(doc_id).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        items.append(BatchItem(result=res, qa=qa, seconds=elapsed))
        origen[doc_id] = om.get("source_kind", "?")

    metrics = batch_metrics(items)
    report = {
        "metrics": metrics.to_dict(),
        "documents": [
            {
                "doc_id": it.result.doc_id,
                "tipo": it.result.tipo_documento,
                "idioma": it.result.idioma_principal,
                "qa_ok": it.qa.is_ok,
                "source_kind": origen.get(it.result.doc_id),
                "gates": [f.gate for f in it.qa.failures],
            }
            for it in items
        ],
    }
    workspace.report_path.parent.mkdir(parents=True, exist_ok=True)
    workspace.report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
