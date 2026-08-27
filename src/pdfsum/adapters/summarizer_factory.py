"""Fábrica del Summarizer: elige backend (local u nube) y resuelve modelo.

Orden de resolución del BACKEND:
  1. flag CLI (--backend)
  2. variable de entorno PDFSUM_SUMMARIZER_BACKEND
  3. .pdfsum-config.json -> "summarizer_backend"
  4. default: "ollama"  (sin cambios de config/env, el comportamiento es
     idéntico al de antes de esta fase)

Orden de resolución del MODELO:
  1. flag CLI (--model)
  2. .pdfsum-config.json -> "model" (si backend=ollama) o "cloud_model"
     (para cualquier backend cloud)
  3. default por backend (DEFAULT_MODEL_BY_BACKEND)

Las API keys de los backends cloud NUNCA se leen de .pdfsum-config.json:
solo de variables de entorno (ver ENV_API_KEY). Evita comitear secretos.

NOTA: este módulo importa adaptadores (Ollama/Cloud/Anthropic/Fake); es
capa externa (adapters/), no dominio.
"""

from __future__ import annotations

import os

from ..config import get_config_value

BACKENDS = ("ollama", "openai", "openrouter", "anthropic")

# "Los mismos modelos que tenemos, corriendo en la nube": solo OpenRouter
# hostea de verdad el peso abierto (Qwen) que usamos local -> default real
# equivalente cloud de qwen2.5:7b. OpenAI/Anthropic no hostean Qwen: su
# default es un modelo propio razonable del proveedor. Todo overrideable
# con --model / "cloud_model" en .pdfsum-config.json.
DEFAULT_MODEL_BY_BACKEND = {
    "ollama": "qwen2.5:7b",
    "openrouter": "qwen/qwen-2.5-7b-instruct",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
}

ENV_API_KEY = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def resolve_backend(explicit: str | None) -> str:
    """Resuelve el backend: flag > env PDFSUM_SUMMARIZER_BACKEND > config > ollama."""
    backend = (
        explicit
        or os.getenv("PDFSUM_SUMMARIZER_BACKEND")
        or get_config_value("summarizer_backend", "ollama")
    )
    if backend not in BACKENDS:
        raise ValueError(
            f"backend '{backend}' desconocido; opciones: {', '.join(BACKENDS)}"
        )
    return backend


def resolve_model(backend: str, explicit: str | None) -> str:
    """Resuelve el modelo: flag > config (model/cloud_model) > default del backend."""
    if explicit:
        return explicit
    key = "model" if backend == "ollama" else "cloud_model"
    configured = get_config_value(key, None)
    return configured or DEFAULT_MODEL_BY_BACKEND[backend]


def build_summarizer(backend: str, model: str, dry_run: bool = False):
    """Instancia el adaptador Summarizer correspondiente al backend resuelto."""
    if dry_run:
        from .fake_summarizer import FakeSummarizer

        return FakeSummarizer()
    if backend == "ollama":
        from .ollama_summarizer import OllamaSummarizer

        return OllamaSummarizer(model=model)
    if backend == "anthropic":
        from .anthropic_summarizer import AnthropicSummarizer

        return AnthropicSummarizer(model=model)
    if backend in ("openai", "openrouter"):
        from .cloud_summarizer import CloudSummarizer

        return CloudSummarizer(provider=backend, model=model)
    raise ValueError(f"backend '{backend}' desconocido; opciones: {', '.join(BACKENDS)}")
