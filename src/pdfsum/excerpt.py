"""Estrategia de porción del texto a resumir (DOMINIO PURO).

Decide QUÉ parte del documento alimentar al modelo según su tipo y estructura,
en lugar de cortar a ciegas los primeros N caracteres (problema del piloto).

- ARTICULO: abstract + introducción + conclusiones (lo esencial de un paper).
- MANUAL: portada/apresentação + índice/sumário + introducción (representativo).
- DIVULGACION: texto completo (son cortos).

Si el documento cabe en el presupuesto, se devuelve completo. Solo cuando
excede, se aplica la estrategia estructural.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contract import DocType

DEFAULT_MAX_CHARS = 42000

# Encabezados estructurales -> etiqueta canónica (pt/es/en).
_STRUCTURE = [
    ("sumario", r"(?im)^\s*(SUM[ÁA]RIO|[ÍI]NDICE|TABLE OF CONTENTS|CONTENTS)\b"),
    (
        "apresentacao",
        (
            r"(?im)^\s*(APRESENTA[ÇC][ÃA]O|PREF[ÁA]CIO|PRESENTACI[ÓO]N|"
            r"PREFACE|FOREWORD|PR[ÓO]LOGO)\b"
        ),
    ),
    (
        "introducao",
        (
            r"(?im)^\s*(INTRODU[ÇC][ÃA]O|INTRODUCCI[ÓO]N|INTRODUCTION|"
            r"1\.?\s+INTRODU)\b"
        ),
    ),
    (
        "conclusao",
        (
            r"(?im)^\s*(CONCLUS[ÕO]ES?|CONCLUSIONES?|CONCLUSIONS?|"
            r"CONSIDERA[ÇC][ÕO]ES\s+FINAIS)\b"
        ),
    ),
    ("abstract", r"(?im)^\s*(RESUMO|ABSTRACT|RESUMEN|R[ÉE]SUM[ÉE])\b"),
]


@dataclass
class Section:
    name: str
    start: int


@dataclass
class Excerpt:
    """Porción seleccionada + metadatos de cómo se construyó."""

    text: str
    parts: list[str] = field(default_factory=list)
    truncated: bool = False
    strategy: str = "full"


def find_structural_sections(text: str) -> list[Section]:
    """Localiza encabezados estructurales con su offset, ordenados por posición."""
    found: list[Section] = []
    for name, pat in _STRUCTURE:
        m = re.search(pat, text)
        if m:
            found.append(Section(name=name, start=m.start()))
    found.sort(key=lambda s: s.start)
    return found


def _window(text: str, start: int, size: int) -> str:
    return text[start : start + size].strip()


def _articulo_excerpt(text: str, max_chars: int) -> Excerpt:
    """Abstract + introducción + conclusiones (paper)."""
    secs = {s.name: s.start for s in find_structural_sections(text)}
    parts: list[str] = []
    used = []
    # presupuesto repartido: abstract e intro y conclusiones
    budget = max_chars
    order = [("abstract", 0.4), ("introducao", 0.3), ("conclusao", 0.3)]
    chunks: list[tuple[str, str]] = []
    for name, frac in order:
        if name in secs:
            size = int(max_chars * frac)
            chunks.append((name, _window(text, secs[name], size)))
    if not chunks:
        # sin estructura reconocible: prefijo (mejor que nada) marcado truncado
        return Excerpt(
            text=text[:max_chars].strip(),
            parts=["prefijo"],
            truncated=len(text) > max_chars,
            strategy="articulo",
        )
    total = 0
    sep = 2  # "\n\n" entre partes
    for name, chunk in chunks:
        extra = sep if parts else 0
        if total + extra + len(chunk) > budget:
            chunk = chunk[: max(0, budget - total - extra)]
        if chunk.strip():
            parts.append(chunk)
            used.append(name)
            total += extra + len(chunk)
    return Excerpt(
        text="\n\n".join(parts), parts=used, truncated=True, strategy="articulo"
    )


def _manual_excerpt(text: str, max_chars: int) -> Excerpt:
    """Portada/apresentação + índice + introducción (representativo)."""
    secs = find_structural_sections(text)
    parts: list[str] = []
    used: list[str] = []
    # portada = arranque del documento
    head = text[: int(max_chars * 0.25)].strip()
    if head:
        parts.append(head)
        used.append("portada")
    budget = max_chars - len(head)
    for name in ("apresentacao", "sumario", "introducao"):
        s = next((x for x in secs if x.name == name), None)
        if s and budget > 0:
            size = min(int(max_chars * 0.25), budget)
            chunk = _window(text, s.start, size)
            if chunk:
                parts.append(chunk)
                used.append(name)
                budget -= len(chunk)
    joined = "\n\n".join(parts)[:max_chars].strip()
    return Excerpt(text=joined, parts=used, truncated=True, strategy="manual")


def select_excerpt(
    text: str, doc_type: DocType, max_chars: int = DEFAULT_MAX_CHARS
) -> Excerpt:
    """Devuelve la porción a resumir según tipo/estructura/tamaño.

    Si el documento cabe en max_chars, se devuelve completo (strategy='full').
    """
    if len(text) <= max_chars:
        return Excerpt(
            text=text.strip(), parts=["completo"], truncated=False, strategy="full"
        )
    if doc_type == DocType.ARTICULO:
        return _articulo_excerpt(text, max_chars)
    if doc_type == DocType.MANUAL:
        return _manual_excerpt(text, max_chars)
    # DIVULGACION largo (raro): prefijo honesto
    return Excerpt(
        text=text[:max_chars].strip(),
        parts=["prefijo"],
        truncated=True,
        strategy="divulgacion",
    )
