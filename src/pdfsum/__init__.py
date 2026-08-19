"""pdfsum — motor de resúmenes estructurados de documentos PDF.

Fase 0: núcleo consolidado (dominio + contrato JSON + puertos).
Arquitectura hexagonal: `contract`, `classify`, `abstracts`, `templates`,
`pipeline` son DOMINIO puro; `adapters/` implementa los puertos.
"""
from .contract import (
    CONTRACT_VERSION,
    Abstract,
    DocType,
    SourceKind,
    Summarizer,
    SummarizeRequest,
    SummaryResult,
)
from .pipeline import summarize_document

__all__ = [
    "CONTRACT_VERSION",
    "Abstract",
    "DocType",
    "SourceKind",
    "SummarizeRequest",
    "Summarizer",
    "SummaryResult",
    "summarize_document",
]
