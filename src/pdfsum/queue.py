"""Cola de jobs por lotes (DOMINIO, orquestación).

Procesa una lista de trabajos con idempotencia y reintentos, persistiendo el
estado vía el PUERTO JobStore (el backend concreto es un adaptador). No importa
adaptadores ni procesos externos: recibe una función `work` inyectada.

Idempotencia: la clave de un job es doc_id + hash del contenido de entrada; un
job ya 'done' con la misma clave no se reprocesa.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from .contract import JobStore

# Estados posibles de un job.
PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


def job_key(doc_id: str, payload: str) -> str:
    """Clave idempotente: doc_id + hash corto del contenido de entrada."""
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{doc_id}:{h}"


@dataclass
class Job:
    key: str
    doc_id: str
    state: str = PENDING
    attempts: int = 0
    error: str = ""
    result: dict | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "doc_id": self.doc_id,
            "state": self.state,
            "attempts": self.attempts,
            "error": self.error,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Job:
        return cls(**d)


class JobQueue:
    """Cola con idempotencia y reintentos sobre un JobStore inyectado."""

    def __init__(self, store: JobStore, max_retries: int = 2):
        self.store = store
        self.max_retries = max_retries

    def _load(self, key: str) -> Job | None:
        raw = self.store.get(key)
        return Job.from_dict(raw) if raw else None

    def _save(self, job: Job) -> None:
        self.store.put(job.key, job.to_dict())

    def submit(
        self,
        doc_id: str,
        payload: str,
        work: Callable[[str, str], dict],
    ) -> Job:
        """Procesa un job idempotente. `work(doc_id, payload)->dict` hace el trabajo.

        Si ya existe un job 'done' con la misma clave, lo devuelve sin reejecutar.
        Reintenta hasta max_retries+1 intentos si `work` lanza excepción.
        """
        key = job_key(doc_id, payload)
        existing = self._load(key)
        if existing and existing.state == DONE:
            return existing  # idempotente: no reprocesar

        job = existing or Job(key=key, doc_id=doc_id)
        while job.attempts <= self.max_retries:
            job.attempts += 1
            job.state = RUNNING
            self._save(job)
            try:
                job.result = work(doc_id, payload)
                job.state = DONE
                job.error = ""
                self._save(job)
                return job
            except Exception as exc:  # noqa: BLE001 (registrar y reintentar)
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = FAILED
                self._save(job)
        return job

    def counts(self) -> dict[str, int]:
        """Recuento de jobs por estado."""
        out: dict[str, int] = {}
        for raw in self.store.all().values():
            out[raw["state"]] = out.get(raw["state"], 0) + 1
        return out
