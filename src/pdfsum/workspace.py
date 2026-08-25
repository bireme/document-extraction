"""Almacén canónico de artefactos del flujo (DOMINIO PURO).

Define el layout de directorios donde viven los artefactos del pipeline, desde
la fuente (PDF) hasta la salida. Solo compone rutas; no hace IO (eso es de los
adaptadores/runner).

Layout:
  <root>/
    ocr/<doc_id>.txt         transcripciones (artefacto intermedio cacheado)
    summaries/<doc_id>.json  resúmenes estructurados
    summaries/report.json    reporte agregado del lote
    lilacs.json              export de catalogación (borrador)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root))

    @property
    def ocr_dir(self) -> Path:
        return self.root / "ocr"

    @property
    def summaries_dir(self) -> Path:
        return self.root / "summaries"

    def ocr_path(self, doc_id: str) -> Path:
        return self.ocr_dir / f"{doc_id}.txt"

    def summary_path(self, doc_id: str) -> Path:
        return self.summaries_dir / f"{doc_id}.json"

    @property
    def report_path(self) -> Path:
        return self.summaries_dir / "report.json"

    @property
    def lilacs_path(self) -> Path:
        return self.root / "lilacs.json"
