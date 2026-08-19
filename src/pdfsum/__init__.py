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
from .metrics import BatchItem, BatchMetrics, batch_metrics
from .pipeline import summarize_document, summarize_pdf
from .qa import QAReport, check_result
from .queue import JobQueue

__version__ = "0.3.0"  # Fase 2 (operación por lotes: QA, cola, métricas)

__all__ = [
    "CONTRACT_VERSION",
    "Abstract",
    "BatchItem",
    "BatchMetrics",
    "DocType",
    "Excerpt",
    "JobQueue",
    "QAReport",
    "SourceKind",
    "SummarizeRequest",
    "Summarizer",
    "SummaryResult",
    "Transcriber",
    "TranscriptResult",
    "__version__",
    "batch_metrics",
    "check_result",
    "select_excerpt",
    "summarize_document",
    "summarize_pdf",
]
