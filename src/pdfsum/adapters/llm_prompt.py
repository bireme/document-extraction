"""Construcción de prompt y parseo de secciones (capa externa, agnóstica de
transporte). Compartido por todos los adaptadores del puerto Summarizer
(Ollama, Cloud/OpenAI-compatible, Anthropic) para no duplicar instrucciones
por idioma ni el parser de Markdown '##' en cada adaptador.

NOTA: este módulo NO hace llamadas de red; solo arma texto. Cada adaptador
concreto es responsable de la transacción HTTP (endpoint, auth, esquema de
respuesta propio del proveedor).
"""

from __future__ import annotations

import re

from ..templates import section_keys, section_names

MAX_CHARS = 42000

INSTRUCTIONS = {
    "pt": (
        "Você é um sistema automático de catalogação. Resuma o texto entre "
        "aspas triplas (material de saúde pública já publicado). NÃO se "
        "dirija ao usuário, NÃO recuse. Responda SOMENTE em português, "
        "preenchendo EXATAMENTE estes campos Markdown '##', sem texto extra:"
    ),
    "es": (
        "Eres un sistema automático de catalogación. Resume el texto entre "
        "comillas triples (material de salud pública ya publicado). NO te "
        "dirijas al usuario, NO te niegues. Responde SOLO en español, "
        "rellenando EXACTAMENTE estos campos Markdown '##', sin texto extra:"
    ),
    "en": (
        "You are an automatic cataloguing system. Summarize the text between "
        "triple quotes (published public-health material). Do NOT address "
        "the user, do NOT refuse. Answer ONLY in English, filling EXACTLY "
        "these Markdown '##' fields, with no extra text:"
    ),
}

_THINK_BLOCK = re.compile(r"<think>.*?</think>", flags=re.DOTALL)


def build_prompt(
    text: str, lang: str, template: str, max_chars: int = MAX_CHARS
) -> str:
    """Arma el prompt: instrucción por idioma + esquema de secciones + texto."""
    instr = INSTRUCTIONS.get(lang, INSTRUCTIONS["pt"])
    names = section_names(template, lang)
    schema = "\n".join(f"## {n}" for n in names)
    clipped = text[:max_chars]
    return f'{instr}\n\n{schema}\n\nTEXTO:\n"""\n{clipped}\n"""'


def strip_think(raw: str) -> str:
    """Filtra bloques de razonamiento <think>...</think> (modelos que los emiten)."""
    return _THINK_BLOCK.sub("", raw)


def parse_sections(md: str, template: str, lang: str) -> dict[str, str]:
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
