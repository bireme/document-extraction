"""Adaptadores del puerto JobStore.

- MemoryJobStore: en memoria (tests).
- FileJobStore: persistencia en un archivo JSON local (producción ligera).

La persistencia en archivo es suficiente para operación por lotes local; un
backend SQLite/Redis sería otro adaptador sin tocar el dominio.
"""

from __future__ import annotations

import json
from pathlib import Path

from .observability import atomic_write_json


class MemoryJobStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value

    def all(self) -> dict[str, dict]:
        return dict(self._data)


class FileJobStore:
    """Persiste el estado de la cola en un JSON (se reescribe en cada put)."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _flush(self) -> None:
        atomic_write_json(self.path, self._data)

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value
        self._flush()

    def all(self) -> dict[str, dict]:
        return dict(self._data)
