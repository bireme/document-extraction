"""Adaptador Anthropic (API nativa Messages) del puerto Summarizer.

Esquema propio de Anthropic (distinto del Chat Completions de OpenAI):
header `x-api-key` + `anthropic-version` (no Bearer), y la respuesta viene
en `content: [{"type": "text", "text": ...}]` en vez de `choices[0].message`.
Por eso es un adaptador separado de `cloud_summarizer.py` y no un `provider`
más del mismo cliente.

NOTA: este módulo SÍ puede tocar red externa; es un adaptador, no dominio.
"""

from __future__ import annotations

import json
import os
import urllib.request

from ..contract import SummarizeRequest
from .llm_prompt import MAX_CHARS, build_prompt, parse_sections, strip_think

ENV_API_KEY = "ANTHROPIC_API_KEY"
ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicSummarizer:
    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        api_key: str | None = None,
        max_tokens: int = 4096,
        timeout: int = 600,
    ):
        self.model = model
        self.api_key = api_key or os.getenv(ENV_API_KEY, "")
        self.max_tokens = max_tokens
        self.timeout = timeout

    def _call(self, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError(
                "falta API key para el backend 'anthropic'. "
                f"Configúrala con la variable de entorno {ENV_API_KEY}."
            )
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": API_VERSION,
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return "".join(block.get("text", "") for block in data.get("content", []))

    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        prompt = build_prompt(req.text, req.lang, req.template, MAX_CHARS)
        raw = strip_think(self._call(prompt))
        return parse_sections(raw, req.template, req.lang)
