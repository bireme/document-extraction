"""Extracción por lote de resúmenes presentes en los documentos."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..abstract_refine import ABSTRACT_REFINE_CONTEXT_CHARS, refine_abstracts
from ..abstracts import extract_abstracts
from ..contract import TextLLM, Transcriber
from ..workspace import Workspace


def extract_abstracts_from_pdfs(
    in_dir: str,
    workspace: Workspace,
    transcriber: Transcriber,
    llm: TextLLM,
    context_chars: int = ABSTRACT_REFINE_CONTEXT_CHARS,
) -> dict:
    """Transcribe los PDFs y extrae solamente los resúmenes de origen."""

    workspace.ocr_dir.mkdir(parents=True, exist_ok=True)
    workspace.abstracts_dir.mkdir(parents=True, exist_ok=True)

    documentos = []

    for pdf in sorted(Path(in_dir).glob("*.pdf")):
        doc_id = pdf.stem
        ocr_file = workspace.ocr_path(doc_id)

        if ocr_file.exists():
            text = ocr_file.read_text(
                encoding="utf-8",
                errors="replace",
            )
            source_kind = "cached"
        else:
            tr = transcriber.transcribe(str(pdf))
            text = tr.text
            source_kind = tr.source_kind.value

            ocr_file.write_text(
                text,
                encoding="utf-8",
            )

        abstracts = extract_abstracts(text)
        try:
            abstracts = refine_abstracts(text, abstracts, llm, context_chars)
        except Exception as exc:  # noqa: BLE001 — aislar fallos del LLM por documento
            logging.getLogger(__name__).warning(
                "Revisión de resúmenes fallida; se conserva la extracción: %s (%s)",
                doc_id,
                type(exc).__name__,
                extra={"doc_id": doc_id, "event": "abstract_refine_fallback"},
            )

        resultado = {
            "doc_id": doc_id,
            "status": "found" if abstracts else "not_found",
            "source_kind": source_kind,
            "abstracts": [
                {
                    "lang": abstract.lang,
                    "header": abstract.header,
                    "text": abstract.text,
                    "keywords": abstract.keywords,
                }
                for abstract in abstracts
            ],
        }

        workspace.abstract_path(doc_id).write_text(
            json.dumps(
                resultado,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        documentos.append(resultado)

    encontrados = sum(1 for documento in documentos if documento["status"] == "found")

    return {
        "total": len(documentos),
        "found": encontrados,
        "not_found": len(documentos) - encontrados,
        "documents": documentos,
    }
