"""Extracción de resúmenes de origen multilingües (DOMINIO PURO).

Localiza los bloques RESUMO/ABSTRACT/RESUMEN/... y los preserva VERBATIM, cada
uno etiquetado con su idioma, sin traducir ni fusionar. Portado y consolidado
desde el piloto (extract_abstracts.py), aquí como función pura del dominio.
"""
from __future__ import annotations

import re

from .contract import Abstract

# Encabezados de bloque de resumen -> idioma.
_HEADERS = [
    ("RESUMO", "pt"), ("ABSTRACT", "en"), ("RESUMEN", "es"),
    ("RÉSUMÉ", "fr"), ("RESUME", "fr"), ("RIASSUNTO", "it"),
    ("ZUSAMMENFASSUNG", "de"),
]
_HEADER_TO_LANG = {h.upper(): lg for h, lg in _HEADERS}

_HEADER_RE = re.compile(
    r"(?im)^\s*(" + "|".join(h for h, _ in _HEADERS) + r")\s*[:.\-]?\s*"
)
_KW_RE = re.compile(
    r"(?i)\b(Palavras[- ]chave|Palabras[- ]llave|Keywords?|"
    r"Palabras\s+clave|Mots[- ]cl[ée]s|Descritores|Descriptors)\b\s*[:.\-]?\s*"
)
_BODY_START_RE = re.compile(
    r"(?im)^\s*(Introdu[cç][aã]o|Introduction|Introducci[oó]n|"
    r"1\.?\s+Introdu|Background)\b"
)
_CUT_TAIL = [
    r"(?i)\bCom\.\s*Ci[eê]ncias\s+Sa[uú]de\b",
    r"(?i)\bRev\.?\s*[A-Z][a-z]+\.?\s*\d{4}",
    r"(?i)\bTelefone\b", r"(?i)\bE[- ]?mail\b", r"(?i)\bEndere[cç]o\b",
    r"(?i)\bPalabras[- ]llave\b",
]

_MIN_BODY = 40
_MAX_BODY = 2500


def extract_abstracts(text: str) -> list[Abstract]:
    """Devuelve bloques de resumen de origen verbatim (lista vacía si no hay)."""
    matches = list(_HEADER_RE.finditer(text))
    out: list[Abstract] = []
    for i, m in enumerate(matches):
        header = m.group(1).upper()
        lang = _HEADER_TO_LANG[header]
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()

        kw = ""
        kwm = _KW_RE.search(chunk)
        if kwm:
            body = chunk[: kwm.start()].strip()
            kw = re.split(r"\n\s*\n", chunk[kwm.end():].strip())[0].strip()
        else:
            body = chunk

        bs = _BODY_START_RE.search(body)
        if bs and bs.start() > 200:
            body = body[: bs.start()].strip()

        body = re.sub(r"\s+", " ", " ".join(body.split("\n"))).strip()
        for cr in _CUT_TAIL:
            body = re.split(cr, body)[0].strip()
        if len(body) > _MAX_BODY:
            body = body[:_MAX_BODY].rsplit(".", 1)[0].strip() + "."
        if len(body) < _MIN_BODY:
            continue
        out.append(Abstract(lang=lang, header=header, text=body, keywords=kw))
    return out


def abstract_langs(abstracts: list[Abstract]) -> list[str]:
    """Idiomas presentes, en orden de aparición y sin duplicados."""
    seen: list[str] = []
    for a in abstracts:
        if a.lang not in seen:
            seen.append(a.lang)
    return seen
