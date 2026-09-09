"""Adaptador FAKE del puerto Summarizer (para tests y --dry-run).

No usa modelos: rellena el esquema de la plantilla con texto determinista
derivado de la petición. Permite validar el contrato y la CLI sin GPU/Ollama.
"""

from __future__ import annotations

import json

from ..contract import SummarizeRequest
from ..templates import section_names


class FakeSummarizer:
    """Implementa el Protocol Summarizer con salida determinista."""

    def __init__(self, json_response: str | None = None):
        self.json_response = json_response

    def complete_json(self, prompt: str) -> str:
        """Permite respuestas programadas; por defecto conserva candidatos."""
        if self.json_response is not None:
            return self.json_response
        data = json.loads(prompt.split("\n")[-1])
        return json.dumps({"abstracts": data["candidates"]}, ensure_ascii=False)

    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        preview = " ".join(req.text.split()[:12])
        out: dict[str, str] = {}
        for name in section_names(req.template):
            out[name] = f"[fake:{req.lang}] {name}: {preview}".strip()
        return out
