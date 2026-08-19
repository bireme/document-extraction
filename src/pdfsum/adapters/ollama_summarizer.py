"""Adaptador Ollama del puerto Summarizer (capa externa).

Invoca un LLM local vía la API HTTP de Ollama con num_ctx amplio (lección
crítica del piloto: el default 4096 trunca en silencio). Construye el prompt a
partir de la plantilla y el idioma, y devuelve las secciones parseadas.

NOTA: este módulo SÍ puede tocar procesos/red externos; es un adaptador, no
dominio. El dominio solo conoce el Protocol `Summarizer`.
"""
from __future__ import annotations

import json
import re
import urllib.request

from ..contract import SummarizeRequest
from ..templates import section_keys, section_names

_ENDPOINT = "http://localhost:11434/api/generate"
_DEFAULT_NUM_CTX = 16384
_MAX_CHARS = 42000

_INSTRUCTIONS = {
    "pt": ("Você é um sistema automático de catalogação. Resuma o texto entre "
           "aspas triplas (material de saúde pública já publicado). NÃO se "
           "dirija ao usuário, NÃO recuse. Responda SOMENTE em português, "
           "preenchendo EXATAMENTE estes campos Markdown '##', sem texto extra:"),
    "es": ("Eres un sistema automático de catalogación. Resume el texto entre "
           "comillas triples (material de salud pública ya publicado). NO te "
           "dirijas al usuario, NO te niegues. Responde SOLO en español, "
           "rellenando EXACTAMENTE estos campos Markdown '##', sin texto extra:"),
    "en": ("You are an automatic cataloguing system. Summarize the text between "
           "triple quotes (published public-health material). Do NOT address "
           "the user, do NOT refuse. Answer ONLY in English, filling EXACTLY "
           "these Markdown '##' fields, with no extra text:"),
}


class OllamaSummarizer:
    def __init__(self, model: str = "qwen2.5:7b",
                 num_ctx: int = _DEFAULT_NUM_CTX, endpoint: str = _ENDPOINT):
        self.model = model
        self.num_ctx = num_ctx
        self.endpoint = endpoint

    def _prompt(self, req: SummarizeRequest) -> str:
        instr = _INSTRUCTIONS.get(req.lang, _INSTRUCTIONS["pt"])
        names = section_names(req.template, req.lang)
        schema = "\n".join(f"## {n}" for n in names)
        text = req.text[:_MAX_CHARS]
        return f'{instr}\n\n{schema}\n\nTEXTO:\n"""\n{text}\n"""'

    def _call(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"num_ctx": self.num_ctx, "temperature": 0.2},
        }).encode("utf-8")
        r = urllib.request.Request(
            self.endpoint, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(r, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8")).get("response", "")

    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        raw = self._call(self._prompt(req))
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
        return _parse_sections(raw, req.template, req.lang)


def _parse_sections(md: str, template: str, lang: str) -> dict[str, str]:
    """Parsea '## Etiqueta\\ncontenido' en {clave_canonica: contenido}."""
    names = section_names(template, lang)
    keys = section_keys(template)
    label_to_key = dict(zip(names, keys))
    out: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in md.splitlines():
        m = re.match(r"^\s*##\s+(.*?)\s*$", line)
        if m:
            if current:
                out[current] = "\n".join(buf).strip()
            label = m.group(1).strip()
            current = label_to_key.get(label, _closest_key(label, label_to_key))
            buf = []
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out


def _closest_key(label: str, label_to_key: dict[str, str]) -> str:
    low = label.lower()
    for lbl, key in label_to_key.items():
        if lbl.lower() in low or low in lbl.lower():
            return key
    return label
