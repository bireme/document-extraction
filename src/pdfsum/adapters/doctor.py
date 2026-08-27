"""Verificador de entorno (adaptador): comprueba dependencias de sistema/modelos.

Reporta el estado de cada requisito sin lanzar excepciones, para que un tercero
pueda diagnosticar su instalación (`pdfsum doctor`). Distingue requisitos DUROS
(flujo nativo: poppler) de OPCIONALES (OCR de imagen: tesseract; resumen:
ollama+modelos; escaneos difíciles: VLM).

Este módulo SÍ puede tocar procesos externos; es un adaptador.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

# Modelos recomendados (por defecto del producto).
DEFAULT_TEXT_MODEL = "qwen2.5:7b"
DEFAULT_VLM_MODEL = "qwen3-vl:8b-instruct"
_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_TAGS = f"{_OLLAMA_HOST}/api/tags"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hard: bool  # True = requisito duro para el flujo mínimo (nativo)


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _tesseract_langs() -> list[str]:
    if not _tool("tesseract"):
        return []
    try:
        out = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
        return [ln.strip() for ln in out.splitlines()[1:] if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def _ollama_models() -> list[str] | None:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def check_environment(
    text_model: str = DEFAULT_TEXT_MODEL,
    vlm_model: str = DEFAULT_VLM_MODEL,
    backend: str = "ollama",
) -> list[Check]:
    """Lista de checks del entorno (no lanza).

    `backend` decide cómo se verifica el resumen (núcleo): 'ollama' (local,
    default) chequea Ollama + el modelo de texto; cualquier backend cloud
    ('openai'/'openrouter'/'anthropic') chequea solo la presencia de su
    variable de entorno de API key (sin llamada de red). Ollama se sigue
    reportando SIEMPRE de forma informativa, porque el fallback VLM de OCR
    (escaneos difíciles) es independiente del backend de resumen elegido.
    """
    checks: list[Check] = []

    # poppler (requisito duro: clasificar + extraer nativos + rasterizar)
    for tool in ("pdftotext", "pdfinfo", "pdftoppm"):
        checks.append(
            Check(
                tool,
                bool(_tool(tool)),
                "encontrado" if _tool(tool) else "FALTA (poppler-utils)",
                hard=True,
            )
        )

    # tesseract (opcional: OCR de escaneados)
    has_tess = bool(_tool("tesseract"))
    checks.append(
        Check(
            "tesseract",
            has_tess,
            "encontrado" if has_tess else "falta (OCR de imagen)",
            hard=False,
        )
    )
    langs = _tesseract_langs()
    for lang in ("por", "spa", "eng"):
        checks.append(
            Check(
                f"tesseract-{lang}",
                lang in langs,
                "instalado" if lang in langs else "falta",
                hard=False,
            )
        )

    if backend == "ollama":
        # ollama + modelos (opcional para el arnés, necesario para resumen real)
        models = _ollama_models()
        if models is None:
            checks.append(
                Check("ollama", False, f"no responde en {_OLLAMA_HOST}", hard=False)
            )
        else:
            checks.append(Check("ollama", True, f"{len(models)} modelos", hard=False))
            checks.append(
                Check(
                    f"model:{text_model}",
                    any(m.startswith(text_model) for m in models),
                    "presente"
                    if any(m.startswith(text_model) for m in models)
                    else "falta",
                    hard=False,
                )
            )
            checks.append(
                Check(
                    f"model:{vlm_model}",
                    any(m.startswith(vlm_model.split(":")[0]) for m in models),
                    "presente (o variante)"
                    if any(m.startswith(vlm_model.split(":")[0]) for m in models)
                    else "falta (OCR de imagen)",
                    hard=False,
                )
            )
    else:
        # backend cloud (openai/openrouter/anthropic): solo verifica la API
        # key por env var, sin llamada de red (evita gastar cuota en cada
        # 'doctor'/CI run). Ollama se reporta aparte, informativo, solo
        # para el fallback VLM de OCR (independiente del backend de resumen).
        from .summarizer_factory import ENV_API_KEY

        env_var = ENV_API_KEY.get(backend, "")
        has_key = bool(os.getenv(env_var)) if env_var else False
        checks.append(
            Check(
                f"{backend}_api_key",
                has_key,
                f"configurada (usar\u00e1 modelo '{text_model}')"
                if has_key
                else f"falta (export {env_var}=\"...\")",
                hard=False,
            )
        )
        models = _ollama_models()
        if models is None:
            checks.append(
                Check(
                    "ollama",
                    False,
                    f"no responde en {_OLLAMA_HOST} "
                    "(opcional, solo para OCR de escaneos dif\u00edciles)",
                    hard=False,
                )
            )
        else:
            checks.append(
                Check(
                    "ollama",
                    True,
                    f"{len(models)} modelos (OCR de escaneos dif\u00edciles)",
                    hard=False,
                )
            )
            checks.append(
                Check(
                    f"model:{vlm_model}",
                    any(m.startswith(vlm_model.split(":")[0]) for m in models),
                    "presente (o variante)"
                    if any(m.startswith(vlm_model.split(":")[0]) for m in models)
                    else "falta (OCR de imagen)",
                    hard=False,
                )
            )
    return checks


def environment_ok(checks: list[Check]) -> bool:
    """True si todos los requisitos DUROS están presentes."""
    return all(c.ok for c in checks if c.hard)


def capabilities(checks: list[Check]) -> dict[str, bool]:
    """Qué puede hacer el entorno según las dependencias presentes.

    - extraer_nativo: leer PDFs con texto (poppler).
    - ocr_imagen: transcribir escaneados (poppler + tesseract).
    - resumen: generar resúmenes (ollama + modelo de texto).  <- núcleo
    - ocr_vlm: OCR de escaneos difíciles con visión (ollama + modelo VLM).
    """
    by = {c.name: c.ok for c in checks}
    poppler = by.get("pdftotext") and by.get("pdfinfo") and by.get("pdftoppm")
    text_model = any(
        k.startswith("model:") and "vl" not in k and v for k, v in by.items()
    )
    vlm_model = any(k.startswith("model:") and "vl" in k and v for k, v in by.items())
    api_key_ok = any(k.endswith("_api_key") and v for k, v in by.items())
    return {
        "extraer_nativo": bool(poppler),
        "ocr_imagen": bool(poppler and by.get("tesseract")),
        "resumen": bool(api_key_ok or (by.get("ollama") and text_model)),
        "ocr_vlm": bool(by.get("ollama") and vlm_model),
    }


def summarization_ready(
    model: str = DEFAULT_TEXT_MODEL,
    backend: str = "ollama",
) -> tuple[bool, str]:
    """Preflight de resumen: ¿el backend elegido está listo para resumir?

    'ollama' (local, default): ¿ollama arriba y el modelo disponible? Para
    cualquier backend cloud: ¿está la API key configurada? (sin llamada de
    red real, evita gastar cuota en cada preflight).

    Devuelve (ok, mensaje). El mensaje, si falla, es accionable.
    """
    if backend != "ollama":
        from .summarizer_factory import ENV_API_KEY

        env_var = ENV_API_KEY.get(backend, "")
        if env_var and os.getenv(env_var):
            return True, f"backend '{backend}' configurado (API key en {env_var})."
        return False, (
            f"Backend '{backend}' seleccionado pero falta la API key.\n"
            f"  export {env_var}=\"...\"\n"
            "Diagnóstico: 'pdfsum doctor'. Detalles: INSTALL.md §2."
        )
    models = _ollama_models()
    if models is None:
        return False, (
            f"Ollama no responde en {_OLLAMA_HOST}. Instala/arranca Ollama y "
            "descarga el modelo:\n  ollama pull "
            + model
            + "\nDiagnóstico: 'pdfsum doctor'. Detalles: INSTALL.md §1."
        )
    if not any(m.startswith(model) for m in models):
        return False, (
            f"Ollama está pero falta el modelo '{model}'. Descárgalo:\n"
            f"  ollama pull {model}\n"
            "Diagnóstico: 'pdfsum doctor'. Detalles: INSTALL.md §1."
        )
    return True, f"ollama + modelo '{model}' disponibles."


def format_capabilities(caps: dict[str, bool]) -> str:
    etiquetas = {
        "extraer_nativo": "Extraer PDFs con texto (poppler)",
        "ocr_imagen": "OCR de escaneados (tesseract)",
        "resumen": "Generar resúmenes (backend local u nube)  [núcleo]",
        "ocr_vlm": "OCR de escaneos difíciles (VLM)",
    }
    return "\n".join(
        f"  {'SÍ ' if caps[k] else 'NO '} {etiquetas[k]}" for k in etiquetas
    )


def format_report(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        mark = "OK " if c.ok else "XX "
        tag = "[duro]" if c.hard else "[opc]"
        lines.append(f"  {mark}{tag:7} {c.name}: {c.detail}")
    return "\n".join(lines)
