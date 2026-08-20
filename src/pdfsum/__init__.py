"""pdfsum — motor de resúmenes estructurados de documentos PDF.

Fases 0-2: núcleo + enrutado por tipo + operación por lotes. Arquitectura
hexagonal: `contract`, `classify`, `templates`, `abstracts`, `excerpt`,
`pipeline`, `qa`, `metrics`, `queue` son DOMINIO puro; `adapters/` implementa
los puertos (Summarizer, Transcriber, JobStore).
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
from .export import to_lilacs
from .metrics import BatchItem, BatchMetrics, batch_metrics
from .pipeline import summarize_document, summarize_pdf
from .qa import QAReport, check_result
from .queue import JobQueue
from .review import ReviewRecord, approve, edit_sections, reject

__version__ = "0.4.0"  # Fase 3 (interfaz: revisión, export LILACS, API)

__all__ = [
    "CONTRACT_VERSION",
    "Abstract",
    "BatchItem",
    "BatchMetrics",
    "DocType",
    "Excerpt",
    "JobQueue",
    "QAReport",
    "ReviewRecord",
    "SourceKind",
    "SummarizeRequest",
    "Summarizer",
    "SummaryResult",
    "Transcriber",
    "TranscriptResult",
    "__version__",
    "approve",
    "batch_metrics",
    "check_result",
    "edit_sections",
    "reject",
    "select_excerpt",
    "summarize_document",
    "summarize_pdf",
    "to_lilacs",
]
