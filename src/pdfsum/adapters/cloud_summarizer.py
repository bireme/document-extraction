"""Adaptador OpenAI-compatible del puerto Summarizer (capa externa).

Sirve para OpenAI, OpenRouter y cualquier gateway compatible con la API
Chat Completions de OpenAI (mismo esquema request/response; solo cambia
`base_url` + API key). No añade SDKs: usa `urllib` (mismo patrón que
`ollama_summarizer.py`) para mantener el núcleo con dependencias mínimas.

NOTA: este módulo SÍ puede tocar red externa; es un adaptador, no dominio.
"""

from __future__ import annotations

import json
import os
import urllib.request

from ..contract import SummarizeRequest
from .llm_prompt import MAX_CHARS, build_prompt, parse_sections, strip_think

BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

ENV_API_KEY = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


class CloudSummarizer:
    """Summarizer vía Chat Completions estilo OpenAI (OpenAI, OpenRouter, o
    cualquier gateway compatible pasando `base_url` explícito)."""

    def __init__(
        self,
        provider: str = "openrouter",
        model: str = "qwen/qwen-2.5-7b-instruct",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 600,
    ):
        if base_url is None and provider not in BASE_URLS:
            raise ValueError(
                f"proveedor desconocido '{provider}'; especifica base_url "
                f"o usa uno de: {', '.join(BASE_URLS)}"
            )
        self.provider = provider
        self.model = model
        self.base_url = (base_url or BASE_URLS[provider]).rstrip("/")
        self.api_key = api_key or os.getenv(ENV_API_KEY.get(provider, ""), "")
        self.timeout = timeout

    def _call(self, prompt: str) -> str:
        if not self.api_key:
            env_var = ENV_API_KEY.get(self.provider, "<api_key explícita>")
            raise RuntimeError(
                f"falta API key para el backend '{self.provider}'. "
                f"Configúrala con la variable de entorno {env_var}."
            )
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        prompt = build_prompt(req.text, req.lang, req.template, MAX_CHARS)
        raw = strip_think(self._call(prompt))
        return parse_sections(raw, req.template, req.lang)
