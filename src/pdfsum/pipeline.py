"""Pipeline del motor (DOMINIO): orquesta clasificación + resumen + abstracts.

Depende del PUERTO `Summarizer` (contract.py), nunca de un adaptador concreto.
Recibe el texto ya extraído (la transcripción/OCR es responsabilidad de un
adaptador aguas arriba) y produce un SummaryResult conforme al contrato.
"""

from __future__ import annotations

from .abstracts import abstract_langs, extract_abstracts
from .chapters import detect_chapters
from .chunking import summarize_in_blocks
from .classify import classify_type, detect_language, template_for
from .consolidation import consolidate_sections
from .contract import (
    DocType,
    Summarizer,
    SummarizeRequest,
    SummaryResult,
    Transcriber,
)
from .excerpt import DEFAULT_MAX_CHARS, select_excerpt


def _summarize_chapter(
    chapter_id: str,
    text: str,
    summarizer: Summarizer,
    lang: str,
    template: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[dict[str, str], dict]:
    """Resume un capítulo, sub-dividiendo en bloques si aún es largo.

    Retorna (secciones, meta) donde meta incluye n_bloques y chars.
    """
    if len(text) <= max_chars:
        req = SummarizeRequest(
            doc_id=chapter_id, text=text, lang=lang, template=template
        )
        secciones = summarizer.summarize(req)
        return secciones, {"n_bloques": 1, "chars": len(text)}

    # Sub-dividir en bloques y consolidar parciales
    _, meta = summarize_in_blocks(
        chapter_id, text, summarizer, lang, template, max_chars=max_chars
    )
    # El resultado consolidado ya está en meta (resumen final)
    # Pero necesitamos extraer la parte de secciones consolidadas;
    # reutilizamos summarize_in_blocks que devuelve (secciones, meta)
    secciones, _ = summarize_in_blocks(
        chapter_id, text, summarizer, lang, template, max_chars=max_chars
    )
    return secciones, meta


def _summarize_hierarchical(
    doc_id: str,
    text: str,
    summarizer: Summarizer,
    lang: str,
    template: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[dict[str, str], dict]:
    """Resume por capítulos detectados; retorna (secciones, meta).

    Si no detecta capítulos, degrada a summarize_in_blocks().
    """
    chapters = detect_chapters(text, lang=lang)

    if not chapters:
        # No capítulos encontrados; usar estrategia de bloques
        return summarize_in_blocks(
            doc_id, text, summarizer, lang, template, max_chars=max_chars
        )

    # Resume cada capítulo y consolida
    chapter_summaries = []
    for ch in chapters:
        ch_secciones, _ = _summarize_chapter(
            f"{doc_id}#cap{ch.number}",
            ch.text,
            summarizer,
            lang,
            template,
            max_chars=max_chars,
        )
        chapter_summaries.append(ch_secciones)

    # Consolidación final entre capítulos
    merged = consolidate_sections(chapter_summaries)

    # Si hay más de 1 capítulo, re-resumir la consolidación para mayor síntesis
    if len(chapters) > 1:
        union_text = "\n\n".join(f"{k}:\n{v}" for k, v in merged.items() if v)
        req = SummarizeRequest(
            doc_id=f"{doc_id}#consolidado",
            text=union_text,
            lang=lang,
            template=template,
        )
        final = summarizer.summarize(req)
    else:
        final = merged

    meta = {
        "excerpt_strategy": "hierarchical",
        "excerpt_parts": [f"cap_{ch.number}" for ch in chapters],
        "excerpt_truncated": False,
        "excerpt_chars": len(text),
        "n_capitulos": len(chapters),
    }
    return final, meta


def summarize_document(
    doc_id: str,
    text: str,
    summarizer: Summarizer,
    *,
    pages: int = 1,
    lang: str | None = None,
    doc_type: DocType | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    long_strategy: str = "excerpt",
) -> SummaryResult:
    """Produce el resumen estructurado de un documento ya transcrito.

    - Detecta idioma (si no se fuerza) y resume EN ESE idioma.
    - Detecta tipo (si no se fuerza) -> plantilla.
    - Para documentos que exceden el presupuesto:
        * long_strategy='excerpt' (def): porción por tipo/estructura.
        * long_strategy='blocks': resumen por bloques + consolidación
          (cubre TODO el texto; útil para manuales largos completos).
        * long_strategy='hierarchical': resumen por capítulos + consolidación
          (detecta capítulos, resume cada uno, consolida intra/inter-capítulos).
    - Extrae y preserva abstracts de origen verbatim (del texto COMPLETO).
    """
    doc_lang = lang or detect_language(text)
    if doc_lang == "unknown":
        doc_lang = "pt"  # fallback razonable para el corpus BIREME
    dtype = doc_type or classify_type(text, pages=pages)
    template = template_for(dtype)

    if long_strategy == "hierarchical" and len(text) > max_chars:
        secciones, exc_meta = _summarize_hierarchical(
            doc_id, text, summarizer, doc_lang, template, max_chars=max_chars
        )
    elif long_strategy == "blocks" and len(text) > max_chars:
        secciones, exc_meta = summarize_in_blocks(
            doc_id, text, summarizer, doc_lang, template, max_chars=max_chars
        )
    else:
        # Estrategia de porción: qué parte del texto alimentar al modelo.
        exc = select_excerpt(text, dtype, max_chars=max_chars)
        req = SummarizeRequest(
            doc_id=doc_id, text=exc.text, lang=doc_lang, template=template
        )
        secciones = summarizer.summarize(req)
        exc_meta = {
            "excerpt_strategy": exc.strategy,
            "excerpt_parts": exc.parts,
            "excerpt_truncated": exc.truncated,
            "excerpt_chars": len(exc.text),
        }

    # Los abstracts se extraen del texto COMPLETO (no de la porción).
    abstracts = extract_abstracts(text)

    return SummaryResult(
        doc_id=doc_id,
        idioma_principal=doc_lang,
        tipo_documento=dtype.value,
        plantilla=template,
        secciones=secciones,
        idiomas_resumo_origem=abstract_langs(abstracts),
        abstracts_origem=abstracts,
        meta={"pages": pages, "text_chars": len(text), **exc_meta},
    )


def summarize_pdf(
    path: str,
    transcriber: Transcriber,
    summarizer: Summarizer,
    *,
    doc_id: str | None = None,
    lang: str | None = None,
    doc_type: DocType | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> SummaryResult:
    """Pipeline completo desde un PDF: transcribe (Paso 1) y resume (Paso 2).

    Usa el puerto Transcriber para obtener el texto; el dominio no conoce OCR.
    """
    tr = transcriber.transcribe(path)
    did = doc_id or path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return summarize_document(
        doc_id=did,
        text=tr.text,
        summarizer=summarizer,
        pages=tr.pages,
        lang=lang,
        doc_type=doc_type,
        max_chars=max_chars,
    )
