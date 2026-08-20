"""Verificador de entorno (adaptador): comprueba dependencias de sistema/modelos.

Reporta el estado de cada requisito sin lanzar excepciones, para que un tercero
pueda diagnosticar su instalación (`pdfsum doctor`). Distingue requisitos DUROS
(flujo nativo: poppler) de OPCIONALES (OCR de imagen: tesseract; resumen:
ollama+modelos; escaneos difíciles: VLM).

Este módulo SÍ puede tocar procesos externos; es un adaptador.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

# Modelos recomendados (por defecto del producto).
DEFAULT_TEXT_MODEL = "qwen2.5:7b"
DEFAULT_VLM_MODEL = "qwen3-vl:8b-instruct"
OLLAMA_TAGS = "http://localhost:11434/api/tags"


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
            ["tesseract", "--list-langs"], capture_output=True, text=True,
            timeout=10, check=False,
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
) -> list[Check]:
    """Lista de checks del entorno (no lanza)."""
    checks: list[Check] = []

    # poppler (requisito duro: clasificar + extraer nativos + rasterizar)
    for tool in ("pdftotext", "pdfinfo", "pdftoppm"):
        checks.append(Check(tool, bool(_tool(tool)),
                            "encontrado" if _tool(tool) else "FALTA (poppler-utils)",
                            hard=True))

    # tesseract (opcional: OCR de escaneados)
    has_tess = bool(_tool("tesseract"))
    checks.append(Check("tesseract", has_tess,
                        "encontrado" if has_tess else "falta (OCR de imagen)",
                        hard=False))
    langs = _tesseract_langs()
    for lang in ("por", "spa", "eng"):
        checks.append(Check(f"tesseract-{lang}", lang in langs,
                            "instalado" if lang in langs else "falta",
                            hard=False))

    # ollama + modelos (opcional para el arnés, necesario para resumen real)
    models = _ollama_models()
    if models is None:
        checks.append(Check("ollama", False, "no responde en localhost:11434",
                            hard=False))
    else:
        checks.append(Check("ollama", True, f"{len(models)} modelos", hard=False))
        checks.append(Check(f"model:{text_model}",
                            any(m.startswith(text_model) for m in models),
                            "presente" if any(m.startswith(text_model)
                                              for m in models) else "falta",
                            hard=False))
        checks.append(Check(f"model:{vlm_model}",
                            any(m.startswith(vlm_model.split(':')[0])
                                for m in models),
                            "presente (o variante)" if any(
                                m.startswith(vlm_model.split(':')[0])
                                for m in models) else "falta (OCR de imagen)",
                            hard=False))
    return checks


def environment_ok(checks: list[Check]) -> bool:
    """True si todos los requisitos DUROS están presentes."""
    return all(c.ok for c in checks if c.hard)


def format_report(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        mark = "OK " if c.ok else "XX "
        tag = "[duro]" if c.hard else "[opc]"
        lines.append(f"  {mark}{tag:7} {c.name}: {c.detail}")
    return "\n".join(lines)
