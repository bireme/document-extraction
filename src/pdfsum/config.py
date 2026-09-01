"""Configuración de pdfsum (DOMINIO PURO).

Lee defaults desde `.pdfsum-config.json` en el directorio actual o home,
permitiendo que usuarios configuren comportamiento sin tocar CLI flags.

Orden de búsqueda:
  1. .pdfsum-config.json (en directorio actual)
  2. ~/.pdfsum-config.json (home)
  3. Defaults del código

Formato esperado:
  {
    "long_strategy": "excerpt" | "blocks" | "hierarchical",
    "model": "qwen2.5:7b",
    "vlm_model": "qwen3-vl:8b-instruct"
    "summarizer_backend": "ollama" | "openai" | "openrouter" | "anthropic",
    "cloud_model": "qwen/qwen-2.5-7b-instruct",
    "lang": "por+eng+spa",
    "max_chars": 40000
  }

NOTA: las API keys de backends cloud NUNCA se leen de este archivo (evita
comitear secretos) -- solo de variables de entorno (OPENAI_API_KEY,
OPENROUTER_API_KEY, ANTHROPIC_API_KEY). Ver adapters/summarizer_factory.py.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_config() -> dict:
    """Cargar configuración desde archivo, si existe."""
    candidates = [
        Path(".pdfsum-config.json"),
        Path.home() / ".pdfsum-config.json",
    ]

    for config_file in candidates:
        if config_file.exists():
            try:
                with open(config_file, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

    return {}


def get_config_value(key: str, default: str | None = None) -> str | None:
    """Obtener un valor de configuración con fallback a default."""
    config = load_config()
    return config.get(key, default)
