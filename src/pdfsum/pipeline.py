"""Pipeline del motor (DOMINIO): orquesta clasificación + resumen + abstracts.

Depende del PUERTO `Summarizer` (contract.py), nunca de un adaptador concreto.
Recibe el texto ya extraído (la transcripción/OCR es responsabilidad de un
adaptador aguas arriba) y produce un SummaryResult conforme al contrato.
"""
from __future__ import annotations

from .abstracts import abstract_langs, extract_abstracts
from .classify import classify_type, detect_language, template_for
from .contract import (
    DocType,
    Summarizer,
    SummarizeRequest,
    SummaryResult,
)


def summarize_document(
    doc_id: str,
    text: str,
    summarizer: Summarizer,
    *,
    pages: int = 1,
    lang: str | None = None,
    doc_type: DocType | None = None,
) -> SummaryResult:
    """Produce el resumen estructurado de un documento ya transcrito.

    - Detecta idioma (si no se fuerza) y resume EN ESE idioma.
    - Detecta tipo (si no se fuerza) -> plantilla.
    - Extrae y preserva abstracts de origen verbatim.
    """
    doc_lang = lang or detect_language(text)
    if doc_lang == "unknown":
        doc_lang = "pt"  # fallback razonable para el corpus BIREME
    dtype = doc_type or classify_type(text, pages=pages)
    template = template_for(dtype)

    req = SummarizeRequest(
        doc_id=doc_id, text=text, lang=doc_lang, template=template
    )
    secciones = summarizer.summarize(req)

    abstracts = extract_abstracts(text)

    return SummaryResult(
        doc_id=doc_id,
        idioma_principal=doc_lang,
        tipo_documento=dtype.value,
        plantilla=template,
        secciones=secciones,
        idiomas_resumo_origem=abstract_langs(abstracts),
        abstracts_origem=abstracts,
        meta={"pages": pages, "text_chars": len(text)},
    )
