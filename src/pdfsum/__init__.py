"""pdfsum — motor de resúmenes estructurados de documentos PDF.

Fases 0-2: núcleo + enrutado por tipo + operación por lotes. Arquitectura
hexagonal: `contract`, `classify`, `templates`, `abstracts`, `excerpt`,
`pipeline`, `qa`, `metrics`, `queue` son DOMINIO puro; `adapters/` implementa
los puertos (Summarizer, Transcriber, JobStore).
"""
from .chunking import split_blocks, summarize_in_blocks
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
from .control import ControlCase, evaluate_case, run_control_suite, term_coverage
from .excerpt import Excerpt, select_excerpt
from .export import to_lilacs
from .metrics import BatchItem, BatchMetrics, batch_metrics
from .pipeline import summarize_document, summarize_pdf
from .qa import QAReport, check_result
from .queue import JobQueue
from .review import ReviewRecord, approve, edit_sections, reject
from .workspace import Workspace

__version__ = "0.8.0"  # Fase 7 (paridad OCR con el piloto: fallback VLM)

__all__ = [
    "CONTRACT_VERSION",
    "Abstract",
    "BatchItem",
    "BatchMetrics",
    "ControlCase",
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
    "Workspace",
    "__version__",
    "approve",
    "batch_metrics",
    "check_result",
    "edit_sections",
    "evaluate_case",
    "reject",
    "run_control_suite",
    "select_excerpt",
    "split_blocks",
    "summarize_document",
    "summarize_in_blocks",
    "summarize_pdf",
    "term_coverage",
    "to_lilacs",
]
