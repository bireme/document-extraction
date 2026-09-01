"""Adaptador VLM del puerto PageOCR (Ollama vision, capa externa).

OCR de una imagen de página con un modelo de visión (qwen3-vl), invocado como
en el pilotaje: `ollama run <modelo> "<prompt> <ruta-imagen>"` — prompt e
imagen EN UNA SOLA CADENA argumento, porque pasar la imagen como argumento
separado a veces no la carga (el modelo empieza a razonar sobre el nombre de
archivo en lugar de leerla). Lección del piloto aplicada:
- Prompt positivo y directo (sin 'escape hatch' de rendirse), en el idioma.
- Filtrar el bloque de razonamiento <think>...</think>.
"""

from __future__ import annotations

import re
import subprocess

from ..config import get_config_value

DEFAULT_VLM = "qwen3-vl:8b-instruct"

_PROMPTS = {
    "por": "Transcreva EXATAMENTE o texto desta imagem, palavra por palavra, em português. Não resuma, não invente.",
    "spa": "Transcribe EXACTAMENTE el texto de esta imagen, palabra por palabra, en español. No resumas, no inventes.",
    "eng": "Transcribe the text in this image verbatim, word for word. Do not summarize, do not invent.",
}

# Secuencia ANSI de control que emite ollama (colores/limpieza de línea).
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def resolve_vlm_model(model: str | None) -> str:
    """Resuelve el modelo: flag > config > default."""
    if model:
        return model
    configured = get_config_value("vlm_model", None)
    return configured or DEFAULT_VLM


class VlmPageOCR:
    """Implementa PageOCR invocando `ollama run` (proceso externo)."""

    def __init__(self, model: str = DEFAULT_VLM, timeout: int = 240):
        self.model = model
        self.timeout = timeout

    def ocr_image(self, image_path: str, lang: str) -> str:
        prompt = _PROMPTS.get(lang, _PROMPTS["por"])
        # prompt + ruta EN UNA SOLA CADENA (lección del piloto)
        message = f"{prompt} {image_path}"
        try:
            proc = subprocess.run(
                ["ollama", "run", self.model, message],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            raw = proc.stdout
        except (OSError, subprocess.SubprocessError):
            return ""
        raw = _ANSI.sub("", raw)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
        raw = raw.replace("<think>", "").replace("</think>", "")
        return raw.strip()
