"""Adaptador FAKE del puerto Transcriber (para tests).

Devuelve un texto y metadatos predefinidos, sin tocar PDF/OCR. Permite probar
el pipeline completo (transcribe + resume) sin poppler/Tesseract/Ollama.
"""

from __future__ import annotations

from ..contract import SourceKind, TranscriptResult


class FakeTranscriber:
    """Implementa el Protocol Transcriber con salida fija."""

    def __init__(
        self,
        text: str,
        pages: int = 1,
        source_kind: SourceKind = SourceKind.NATIVO,
        pages_detail: list[dict] | None = None,
    ):
        self._text = text
        self._pages = pages
        self._kind = source_kind
        self._pages_detail = pages_detail

    def transcribe(self, path: str) -> TranscriptResult:
        return TranscriptResult(
            text=self._text,
            pages=self._pages,
            source_kind=self._kind,
            pages_detail=self._pages_detail,
        )
