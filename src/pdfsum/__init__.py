"""pdfsum — motor de resúmenes estructurados de documentos PDF.

Fases 0-1: núcleo + enrutado por tipo. Arquitectura hexagonal: `contract`,
`classify`, `templates`, `abstracts`, `excerpt`, `pipeline` son DOMINIO puro;
`adapters/` implementa los puertos (Summarizer, Transcriber).
"""
from .contract import (
    CONTRACT_VERSION,
    Abstract,
    DocType,
    SourceKind,
    Summarizer,
    SummarizeRequest,
    SummaryResult,
    Transcriber,
    TranscriptResult,
)
from .excerpt import Excerpt, select_excerpt
from .pipeline import summarize_document, summarize_pdf

__version__ = "0.2.0"  # Fase 1 integrada (enrutado por tipo)

__all__ = [
    "CONTRACT_VERSION",
    "Abstract",
    "DocType",
    "Excerpt",
    "SourceKind",
    "SummarizeRequest",
    "Summarizer",
    "SummaryResult",
    "Transcriber",
    "TranscriptResult",
    "__version__",
    "select_excerpt",
    "summarize_document",
    "summarize_pdf",
]
