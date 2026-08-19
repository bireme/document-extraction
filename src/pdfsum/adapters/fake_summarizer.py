"""Adaptador FAKE del puerto Summarizer (para tests y --dry-run).

No usa modelos: rellena el esquema de la plantilla con texto determinista
derivado de la petición. Permite validar el contrato y la CLI sin GPU/Ollama.
"""
from __future__ import annotations

from ..contract import SummarizeRequest
from ..templates import section_names


class FakeSummarizer:
    """Implementa el Protocol Summarizer con salida determinista."""

    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        preview = " ".join(req.text.split()[:12])
        out: dict[str, str] = {}
        for name in section_names(req.template):
            out[name] = f"[fake:{req.lang}] {name}: {preview}".strip()
        return out
