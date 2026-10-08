"""Generación textual y selección del resultado, sin contratos estructurados."""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise

from .chapters import chapter_boundaries
from .chunking import split_blocks
from .classify import classify_type, detect_language
from .contract import Abstract, DocumentAbstractResult, TextGenerator
from .excerpt import select_excerpt


def _resolve_language(text: str, lang: str | None = None) -> str:
    """Aplica el mismo idioma de respaldo a extracción y generación."""
    language = lang or detect_language(text)
    return "pt" if language == "unknown" else language


def _generate(generator: TextGenerator, text: str, lang: str) -> str:
    result = generator.generate_abstract(text, lang)
    if not isinstance(result, str) or not result.strip():
        raise ValueError("El generador devolvió un resumen vacío")
    result = result.strip()
    if result.startswith(("{", "[", "```", "#")):
        raise ValueError("El generador no devolvió solamente texto narrativo")
    return result


def _reduce(partials: list[str], generate: Callable[[str], str], max_chars: int) -> str:
    """Reduce por niveles sin truncar; falla si el modelo no logra comprimir."""
    for _ in range(32):
        joined = "\n\n".join(partials)
        if len(joined) <= max_chars:
            return generate(joined)
        reduced = [generate(block) for block in split_blocks(joined, max_chars)]
        if len("\n\n".join(reduced)) >= len(joined):
            raise ValueError("La reducción no comprime los resúmenes parciales")
        partials = reduced
    raise ValueError("Se excedió el límite de niveles de reducción")


def generate_document_abstract(
    doc_id: str,
    text: str,
    generator: TextGenerator,
    *,
    pages: int = 1,
    lang: str | None = None,
    max_chars: int = 42000,
    long_strategy: str = "hierarchical",
) -> DocumentAbstractResult:
    """Genera un solo abstract final; nunca busca resúmenes existentes."""
    if type(max_chars) is not int or max_chars <= 0:
        raise ValueError("max_chars debe ser un entero positivo")
    if long_strategy not in ("hierarchical", "blocks", "excerpt"):
        raise ValueError("Estrategia de documento largo desconocida")
    if not text.strip():
        raise ValueError("No hay texto para generar el resumen")
    language = _resolve_language(text, lang)
    dtype = classify_type(text, pages=pages)
    strategy = "full"
    covered = len(text)
    calls = 0

    def generate(part: str) -> str:
        nonlocal calls
        calls += 1
        return _generate(generator, part, language)

    if len(text) <= max_chars:
        final = generate(text)
    elif long_strategy == "excerpt":
        excerpt = select_excerpt(text, dtype, max_chars, include_abstract=False)
        final = generate(excerpt.text)
        strategy, covered = "excerpt", len(excerpt.text)
    else:
        # Los offsets incluyen encabezados, prefacio y el último carácter.
        boundaries = chapter_boundaries(text) if long_strategy == "hierarchical" else []
        reliable = bool(boundaries)
        boundaries = boundaries or [0, len(text)]
        strategy = "hierarchical" if reliable else "blocks"
        partials = []
        for start, end in pairwise(boundaries):
            blocks = split_blocks(text[start:end], max_chars)
            chapter = [generate(block) for block in blocks]
            if len(chapter) > 1:
                partials.append(_reduce(chapter, generate, max_chars))
            else:
                partials.extend(chapter)
        final = (
            _reduce(partials, generate, max_chars) if len(partials) > 1 else partials[0]
        )
    return DocumentAbstractResult(
        doc_id,
        language,
        dtype.value,
        ai_generated_abstract=final,
        meta={
            "pages": pages,
            "text_chars": len(text),
            "abstract_source": "generated",
            "excerpt_strategy": strategy,
            "excerpt_chars": covered,
            "excerpt_truncated": covered < len(text),
            "input_calls": calls,
        },
    )


def document_abstract_result(
    doc_id: str,
    text: str,
    generator: TextGenerator,
    abstracts: list[Abstract],
    *,
    pages: int = 1,
    long_strategy: str = "hierarchical",
    max_chars: int = 42000,
) -> DocumentAbstractResult:
    """La lista final de extracción decide si hace falta generar."""
    if abstracts:
        return DocumentAbstractResult(
            doc_id,
            _resolve_language(text),
            classify_type(text, pages=pages).value,
            ai_extracted_abstract=abstracts,
            meta={
                "pages": pages,
                "text_chars": len(text),
                "abstract_source": "extracted",
            },
        )
    return generate_document_abstract(
        doc_id,
        text,
        generator,
        pages=pages,
        long_strategy=long_strategy,
        max_chars=max_chars,
    )
