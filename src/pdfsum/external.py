"""Puertos del flujo externo; los identificadores son opacos para el motor."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

InputType = Literal["pdf", "text"]
Command = Literal["run", "extract-abstracts", "transcribe", "summarize"]
INPUT_TYPES: dict[str, InputType] = {
    "run": "pdf",
    "extract-abstracts": "pdf",
    "transcribe": "pdf",
    "summarize": "text",
}


@dataclass(frozen=True)
class ExternalInput:
    """Entrada con identidad original, tipo explícito y ubicación del recurso."""

    id: object
    input_type: InputType
    url: str


@dataclass(frozen=True)
class ExternalResult:
    """Envelope interno; no prescribe la representación del almacenamiento."""

    id: object
    command: Command
    status: Literal["completed", "failed"]
    result: dict | str | None = None
    phase: str | None = None
    error_type: str | None = None
    error: str | None = None


class InputSource(Protocol):
    """Selecciona/reserva pendientes por comando según la política del adapter.

    Debe excluir éxitos previos y definir reintentos y recuperación de reservas.
    La iteración puede reclamar una entrada justo antes de entregarla.
    """

    def pending(self, command: Command) -> Iterable[ExternalInput]: ...


class ResultStore(Protocol):
    """Persiste éxito/fallo y confirma la reserva según la política del adapter.

    Una excepción no confirma la entrada; el executor detiene el lote para
    evitar perder resultados silenciosamente. La escritura debe ser idempotente.
    """

    def save(self, result: ExternalResult) -> None: ...


class InputMaterializer(Protocol):
    """Materializa en la ruta exclusiva asignada por el executor."""

    def materialize(self, entry: ExternalInput, destination: Path) -> None: ...


class InputProcessor(Protocol):
    """Procesa una entrada local; conserva su propia estructura de resultado."""

    def process(self, command: Command, path: Path) -> dict | str: ...

    def temporary_results(self, command: Command, path: Path) -> Iterable[Path]:
        """Rutas principales creadas por esta entrada; nunca OCR ni logs."""
        ...
