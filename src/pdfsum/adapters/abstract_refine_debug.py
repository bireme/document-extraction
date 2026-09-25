"""Persistencia opt-in de respuestas crudas, separada de los logs operativos."""

from __future__ import annotations

import json
from pathlib import Path


class AbstractRefineDebugSink:
    """El llamador aísla fallos de escritura y avisa sin modificar la revisión."""

    def __init__(self, directory: Path, doc_id: str):
        self.directory = directory / doc_id
        self.doc_id = doc_id
        self.counts: dict[int, int | None] = {}
        self.initialized = False

    def __call__(self, *, attempt: int, raw_response=None, metadata=None) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.initialized:
            # Retira intentos anteriores del documento para evitar diagnósticos viejos.
            for number in (1, 2):
                for suffix in ("response.txt", "validation.json"):
                    (self.directory / f"attempt-{number}-{suffix}").unlink(
                        missing_ok=True
                    )
            self.initialized = True
        if metadata is None:
            # Bytes UTF-8 sin reformateo ni conversión de saltos de línea.
            (self.directory / f"attempt-{attempt}-response.txt").write_bytes(
                raw_response.encode("utf-8")
            )
            self.counts[attempt] = None
            try:
                data = json.loads(raw_response)
                if isinstance(data, dict) and isinstance(data.get("abstracts"), list):
                    self.counts[attempt] = len(data["abstracts"])
            except (ValueError, TypeError):
                pass  # La validación original decide si la respuesta es válida.
        else:
            data = {
                "doc_id": self.doc_id,
                "attempt": attempt,
                "abstracts_returned": self.counts.get(attempt),
                **metadata,
            }
            (self.directory / f"attempt-{attempt}-validation.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
