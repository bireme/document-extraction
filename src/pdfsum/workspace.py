"""Almacén canónico de artefactos del flujo (DOMINIO PURO).

Define el layout de directorios donde viven los artefactos del pipeline, desde
la fuente (PDF) hasta la salida. Solo compone rutas; no hace IO (eso es de los
adaptadores/runner).

Layout:
  <root>/
    ocr/<doc_id>.txt         transcripciones (artefacto intermedio cacheado)
    summaries/<doc_id>.json  resúmenes estructurados
    <logs_dir>/report.json   reporte agregado del lote, si logs_dir fue definido
    <logs_dir>/events.jsonl  eventos durables por documento/fase
    <logs_dir>/infrastructure.jsonl  muestras de CPU/RAM/disco/temperatura/GPU
    summaries/report.json    fallback si logs_dir no fue definido
    lilacs.json              export de catalogación (borrador)
    bibframe/<doc_id>.bibframe.json  registros bibliográficos BIBFRAME (borrador)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SECUENCIA_RUTA_CODIFICADA = re.compile(r"%(?:2e|2f|5c)", re.IGNORECASE)


def _validate_doc_id(doc_id: str) -> str:
    """Rechaza IDs capaces de alterar la ruta canónica del documento."""
    if (
        not doc_id.strip()
        or doc_id in {".", ".."}
        or "/" in doc_id
        or "\\" in doc_id
        or _SECUENCIA_RUTA_CODIFICADA.search(doc_id)
        or any(ord(character) < 32 or ord(character) == 127 for character in doc_id)
    ):
        raise ValueError("ID de documento inválido para construir una ruta")
    return doc_id


@dataclass(frozen=True)
class Workspace:
    root: Path
    logs_dir: Path | None = None

    def __init__(self, root: str | Path, logs_dir: str | Path | None = None) -> None:
        object.__setattr__(self, "root", Path(root))
        object.__setattr__(
            self,
            "logs_dir",
            Path(logs_dir) if logs_dir is not None else None,
        )

    @property
    def ocr_dir(self) -> Path:
        return self.root / "ocr"

    @property
    def summaries_dir(self) -> Path:
        return self.root / "summaries"

    def ocr_path(self, doc_id: str) -> Path:
        return self.ocr_dir / f"{_validate_doc_id(doc_id)}.txt"

    def summary_path(self, doc_id: str) -> Path:
        return self.summaries_dir / f"{_validate_doc_id(doc_id)}.json"

    @property
    def report_path(self) -> Path:
        if self.logs_dir is not None:
            return self.logs_dir / "report.json"
        return self.summaries_dir / "report.json"

    @property
    def lilacs_path(self) -> Path:
        return self.root / "lilacs.json"

    @property
    def bibframe_dir(self) -> Path:
        return self.root / "bibframe"

    def bibframe_path(self, doc_id: str) -> Path:
        return self.bibframe_dir / f"{_validate_doc_id(doc_id)}.bibframe.json"
