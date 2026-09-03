"""Adaptadores del puerto JobStore.

- MemoryJobStore: en memoria (tests).
- FileJobStore: persistencia en un archivo JSON local (producción ligera).
- DirJobStore: un JSON atómico POR JOB (FASE20) — apto para dos procesos
  concurrentes (API encola, worker actualiza) sin last-writer-wins.

La persistencia en archivo es suficiente para operación por lotes local; un
backend SQLite/Redis sería otro adaptador sin tocar el dominio.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .observability import atomic_write_json


class MemoryJobStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._data[key] = value

    def all(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._data)


class DirJobStore:
    """Un fichero JSON por job; lecturas siempre desde disco (multi-proceso).

    FASE20: la API (proceso 1) crea jobs y el worker (proceso 2) los
    actualiza; al ser un fichero por clave con escritura atómica no hay
    pérdida de updates entre procesos.
    """

    def __init__(self, path: str | Path) -> None:
        self.dir = Path(path)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _file(self, key: str) -> Path:
        # la clave del dominio es 'doc_id:hash'; ':' no es apto en ficheros
        safe = key.replace(":", "@")
        if "/" in safe or "\\" in safe or safe in {".", ".."}:
            raise ValueError("clave de job inválida")
        return self.dir / f"{safe}.json"

    def get(self, key: str) -> dict | None:
        f = self._file(key)
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, value: dict) -> None:
        atomic_write_json(self._file(key), value)

    def all(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for f in sorted(self.dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out[d.get("key", f.stem.replace("@", ":"))] = d
        return out


class FileJobStore:
    """Persiste el estado de la cola en un JSON (se reescribe en cada put)."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        self._lock = threading.RLock()
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _flush(self) -> None:
        atomic_write_json(self.path, self._data)

    def get(self, key: str) -> dict | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._data[key] = value
            self._flush()

    def all(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._data)
