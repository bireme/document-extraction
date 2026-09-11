"""Puente por entrada hacia los mismos procesadores usados por la CLI local."""

from __future__ import annotations

import json
from pathlib import Path

from ..abstract_refine import ABSTRACT_REFINE_CONTEXT_CHARS
from ..external import Command
from ..pipeline import summarize_document
from ..workspace import Workspace
from .abstract_batch import extract_abstracts_from_pdfs
from .observability import atomic_write_json
from .pdf_batch import run_batch_pdfs, transcribe_pdfs


def safe_error(exc: BaseException) -> str:
    """No reproduce mensajes de terceros que pueden contener textos o secretos."""
    return "Falló la operación; el detalle del proveedor se omitió por privacidad"


class LocalInputProcessor:
    """Reutiliza los runners PDF con una ruta explícita y el motor de resumen."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        transcriber=None,
        summarizer=None,
        lang: str | None = None,
        pages: int = 1,
        long_strategy: str = "excerpt",
        retranscribe: bool = False,
        context_chars: int = ABSTRACT_REFINE_CONTEXT_CHARS,
    ) -> None:
        self.workspace = workspace
        self.transcriber = transcriber
        self.summarizer = summarizer
        self.lang = lang
        self.pages = pages
        self.long_strategy = long_strategy
        self.retranscribe = retranscribe
        self.context_chars = context_chars

    def temporary_results(self, command: Command, path: Path) -> list[Path]:
        if command == "transcribe":
            # La transcripción es el OCR canónico y se conserva como artefacto.
            return []
        if command == "extract-abstracts":
            return [self.workspace.abstract_path(path.stem)]
        return [self.workspace.summary_path(path.stem)]

    def process(self, command: Command, path: Path) -> dict | str:
        ws = self.workspace
        if command == "run":
            report = run_batch_pdfs(
                str(path.parent),
                ws,
                self.transcriber,
                self.summarizer,
                input_paths=[path],
                long_strategy=self.long_strategy,
                retranscribe=self.retranscribe,
                format_error=safe_error,
            )
            if report["progress"]["failed"]:
                raise RuntimeError("Falló el procesamiento del PDF")
        elif command == "extract-abstracts":
            extract_abstracts_from_pdfs(
                str(path.parent),
                ws,
                self.transcriber,
                self.summarizer,
                self.context_chars,
                input_paths=[path],
                format_error=safe_error,
            )
        elif command == "transcribe":
            transcribe_pdfs(
                str(path.parent),
                ws,
                self.transcriber,
                input_paths=[path],
                retranscribe=self.retranscribe,
            )
            return ws.ocr_path(path.stem).read_text(encoding="utf-8")
        elif command == "summarize":
            result = summarize_document(
                doc_id=path.stem,
                text=path.read_text(encoding="utf-8"),
                summarizer=self.summarizer,
                pages=self.pages,
                lang=self.lang,
            ).to_dict()
            atomic_write_json(ws.summary_path(path.stem), result)
        else:
            raise ValueError("Comando externo no admitido")
        return json.loads(
            self.temporary_results(command, path)[0].read_text(encoding="utf-8")
        )
