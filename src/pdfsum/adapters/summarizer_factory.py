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
    raise ValueError(
        f"backend '{backend}' desconocido; opciones: {', '.join(BACKENDS)}"
    )


DEFAULT_ABSTRACT_MODELS = dict(DEFAULT_MODEL_BY_BACKEND)
DEFAULT_SUMMARY_MODELS = {
    **DEFAULT_MODEL_BY_BACKEND,
    "ollama": "qwen3:8b",
    "openrouter": "qwen/qwen3-8b",
}


def resolve_task_model(backend: str, task: str, explicit: str | None = None) -> str:
    """Resuelve cada responsabilidad: CLI, entorno, configuración, default."""
    if get_config_value("model") or get_config_value("cloud_model"):
        import logging

        logging.getLogger(__name__).warning(
            "model/cloud_model pertenecen al flujo legado; configura abstract_model y summary_model"
        )
    defaults = DEFAULT_ABSTRACT_MODELS if task == "abstract" else DEFAULT_SUMMARY_MODELS
    key = f"{task}_model"
    return (
        explicit
        or os.getenv(f"PDFSUM_{key.upper()}")
        or get_config_value(key)
        or defaults[backend]
    )


class LazyGenerator:
    """Comprueba el generador solamente cuando un documento lo necesita."""

    def __init__(self, backend: str, model: str, dry_run: bool = False):
        self.provider, self.model, self.dry_run = backend, model, dry_run
        self.delegate = None

    def generate_abstract(self, text: str, lang: str) -> str:
        if self.delegate is None:
            if not self.dry_run:
                from .doctor import summarization_ready

                ok, message = summarization_ready(self.model, backend=self.provider)
                if not ok:
                    raise RuntimeError("Generación no disponible: " + message)
            self.delegate = build_summarizer(self.provider, self.model, self.dry_run)
        return self.delegate.generate_abstract(text, lang)


class UnavailableReviewer:
    """Activa el fallback conservador con diagnóstico de disponibilidad."""

    def __init__(self, backend: str, model: str, message: str):
        self.provider, self.model, self.message = backend, model, message

    def complete_json(self, prompt: str) -> str:
        raise RuntimeError(self.message)


def build_reviewer(backend: str, model: str, dry_run: bool = False):
    """La falta del modelo de revisión no bloquea la extracción determinista."""
    if not dry_run:
        from .doctor import summarization_ready

        ok, message = summarization_ready(model, backend=backend)
        if not ok:
            return UnavailableReviewer(backend, model, message)
    return build_summarizer(backend, model, dry_run)


def model_diagnostics(reviewer, generator, source: str) -> dict:
    """Registra las responsabilidades sin atribuir llamadas que se evitaron."""

    def describe(adapter):
        if adapter is None:
            return {"backend": None, "model": None, "used": False}
        if getattr(adapter, "dry_run", False):
            return {"backend": "fake", "model": None}
        return {
            "backend": getattr(
                adapter, "provider", "ollama" if hasattr(adapter, "model") else "fake"
            ),
            "model": getattr(adapter, "model", None),
        }

    return {
        "abstract": describe(reviewer),
        "summary": {**describe(generator), "used": source == "generated"},
    }


def resolve_task_backend(
    task: str, explicit: str | None = None, shared: str | None = None
) -> str:
    """Permite proveedores independientes sin romper --backend compartido."""
    return resolve_backend(
        explicit
        or shared
        or os.getenv(f"PDFSUM_{task.upper()}_BACKEND")
        or os.getenv("PDFSUM_SUMMARIZER_BACKEND")
        or get_config_value(f"{task}_backend")
    )
