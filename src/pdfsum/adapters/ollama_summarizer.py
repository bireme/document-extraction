"""Adaptador Ollama del puerto Summarizer (capa externa).

Invoca un LLM local vía la API HTTP de Ollama con num_ctx amplio (lección
crítica del piloto: el default 4096 trunca en silencio). Construye el prompt a
partir de la plantilla y el idioma, y devuelve las secciones parseadas.

NOTA: este módulo SÍ puede tocar procesos/red externos; es un adaptador, no
dominio. El dominio solo conoce el Protocol `Summarizer`.
"""

from __future__ import annotations

import json
import os
import urllib.request

from ..contract import SummarizeRequest
from .llm_prompt import MAX_CHARS, build_prompt, parse_sections, strip_think

_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
_ENDPOINT = f"{_OLLAMA_HOST}/api/generate"
_DEFAULT_NUM_CTX = 16384


class OllamaSummarizer:
    def __init__(
        self,
        model: str = "qwen2.5:7b",
        num_ctx: int = _DEFAULT_NUM_CTX,
        endpoint: str = _ENDPOINT,
    ):
        self.model = model
        self.num_ctx = num_ctx
        self.endpoint = endpoint

    def _call(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_ctx": self.num_ctx, "temperature": 0.2},
            }
        ).encode("utf-8")
        r = urllib.request.Request(
            self.endpoint, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(r, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8")).get("response", "")

    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        prompt = build_prompt(req.text, req.lang, req.template, MAX_CHARS)
        raw = strip_think(self._call(prompt))
        return parse_sections(raw, req.template, req.lang)
