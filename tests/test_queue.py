"""Tests de la cola de jobs (criterios C6, C7, C8)."""

import unittest

from pdfsum.adapters.job_store import MemoryJobStore
from pdfsum.queue import DONE, FAILED, JobQueue


class TestQueue(unittest.TestCase):
    def test_idempotencia(self):
        """C6: mismo doc+payload no se reprocesa."""
        store = MemoryJobStore()
        q = JobQueue(store)
        calls = {"n": 0}

        def work(doc_id, payload):
            calls["n"] += 1
            return {"ok": True}

        q.submit("d1", "contenido", work)
        q.submit("d1", "contenido", work)  # misma clave
        self.assertEqual(calls["n"], 1)

    def test_reintentos(self):
        """C7: falla -> reintenta hasta max_retries; queda 'failed'."""
        store = MemoryJobStore()
        q = JobQueue(store, max_retries=2)
        attempts = {"n": 0}

        def failing(doc_id, payload):
            attempts["n"] += 1
            raise RuntimeError("boom")

        job = q.submit("d2", "x", failing)
        self.assertEqual(job.state, FAILED)
        self.assertEqual(attempts["n"], 3)  # 1 + 2 reintentos
        self.assertIn("boom", job.error)

    def test_estados(self):
        """C8: transición a done/failed y recuento por estado."""
        store = MemoryJobStore()
        q = JobQueue(store, max_retries=0)
        q.submit("ok1", "a", lambda d, p: {"r": 1})
        q.submit("bad1", "b", lambda d, p: (_ for _ in ()).throw(ValueError("x")))
        counts = q.counts()
        self.assertEqual(counts.get(DONE, 0), 1)
        self.assertEqual(counts.get(FAILED, 0), 1)


if __name__ == "__main__":
    unittest.main()
