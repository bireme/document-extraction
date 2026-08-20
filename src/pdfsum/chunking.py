"""Resumen por bloques con consolidación (DOMINIO PURO).

Para documentos gigantes que exceden el presupuesto y cuyo cuerpo entero
importa (no solo intro/conclusiones): divide el texto en bloques, resume cada
uno vía el puerto Summarizer, y consolida los resúmenes parciales en uno final.

Cubre TODO el texto (sin corte ciego ni pérdida), a diferencia de la porción.
"""
from __future__ import annotations

import re

from .contract import Summarizer, SummarizeRequest

DEFAULT_BLOCK_CHARS = 40000


def split_blocks(text: str, max_chars: int = DEFAULT_BLOCK_CHARS) -> list[str]:
    """Divide el texto en bloques <= max_chars, cortando en párrafos si se puede.

    Garantiza cobertura total: la concatenación de los bloques equivale al texto
    (salvo normalización de espacios en los límites).
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    blocks: list[str] = []
    paras = re.split(r"(\n\s*\n)", text)  # conserva separadores
    buf = ""
    for part in paras:
        if len(buf) + len(part) <= max_chars:
            buf += part
        else:
            if buf.strip():
                blocks.append(buf.strip())
            if len(part) <= max_chars:
                buf = part
            else:
                # párrafo enorme: trocear duro respetando el tamaño
                for i in range(0, len(part), max_chars):
                    piece = part[i:i + max_chars]
                    if len(piece) == max_chars:
                        blocks.append(piece.strip())
                    else:
                        buf = piece
        # si buf ya llenó justo, vaciar
        if len(buf) >= max_chars:
            blocks.append(buf.strip())
            buf = ""
    if buf.strip():
        blocks.append(buf.strip())
    return [b for b in blocks if b]


def summarize_in_blocks(
    doc_id: str,
    text: str,
    summarizer: Summarizer,
    lang: str,
    template: str,
    *,
    max_chars: int = DEFAULT_BLOCK_CHARS,
) -> tuple[dict[str, str], dict]:
    """Resume por bloques y consolida. Devuelve (secciones, meta_bloques).

    Estrategia: resume cada bloque con el mismo esquema, luego consolida
    concatenando el contenido por sección (una segunda pasada del resumidor
    sobre la unión para producir la versión final).
    """
    blocks = split_blocks(text, max_chars=max_chars)
    partials: list[dict[str, str]] = []
    for i, block in enumerate(blocks):
        req = SummarizeRequest(
            doc_id=f"{doc_id}#b{i+1}", text=block, lang=lang, template=template
        )
        partials.append(summarizer.summarize(req))

    # Consolidación: unir por sección y re-resumir esa unión.
    merged: dict[str, str] = {}
    keys = {k for p in partials for k in p}
    for k in keys:
        merged[k] = "\n".join(p.get(k, "") for p in partials if p.get(k)).strip()

    if len(partials) > 1:
        union_text = "\n\n".join(
            f"{k}:\n{v}" for k, v in merged.items() if v
        )
        req = SummarizeRequest(
            doc_id=f"{doc_id}#consolidado", text=union_text,
            lang=lang, template=template,
        )
        final = summarizer.summarize(req)
    else:
        final = merged

    meta = {
        "excerpt_strategy": "blocks",
        "excerpt_parts": [f"bloque_{i+1}" for i in range(len(blocks))],
        "excerpt_truncated": False,
        "excerpt_chars": len(text),
        "n_bloques": len(blocks),
    }
    return final, meta
