"""pdfsum — motor de resúmenes estructurados de documentos PDF.

Fases 0-2: núcleo + enrutado por tipo + operación por lotes. Arquitectura
hexagonal: `contract`, `classify`, `templates`, `abstracts`, `excerpt`,
`pipeline`, `qa`, `metrics`, `queue` son DOMINIO puro; `adapters/` implementa
los puertos (Summarizer, Transcriber, JobStore).
"""

from .abstract_generation import generate_document_abstract
from .chunking import split_blocks, summarize_in_blocks
from .contract import (
    CONTRACT_VERSION,
    DOCUMENT_ABSTRACT_VERSION,
    Abstract,
    DocType,
    DocumentAbstractResult,
    SourceKind,
    Summarizer,
    SummarizeRequest,
    SummaryResult,
    TextGenerator,
    Transcriber,
    TranscriptResult,
    read_result,
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

__version__ = "0.14.0"  # Release 0.14.0 (calidad de transcripción F16-F19)

__all__ = [
    "CONTRACT_VERSION",
    "DOCUMENT_ABSTRACT_VERSION",
    "Abstract",
    "BatchItem",
    "BatchMetrics",
    "ControlCase",
    "DocType",
    "DocumentAbstractResult",
    "Excerpt",
    "JobQueue",
    "QAReport",
    "ReviewRecord",
    "SourceKind",
    "SummarizeRequest",
    "Summarizer",
    "SummaryResult",
    "TextGenerator",
    "Transcriber",
    "TranscriptResult",
    "Workspace",
    "__version__",
    "approve",
    "batch_metrics",
    "check_result",
    "edit_sections",
    "evaluate_case",
    "generate_document_abstract",
    "read_result",
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
