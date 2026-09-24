"""Extracción de resúmenes de origen multilingües (DOMINIO PURO).

Localiza los bloques RESUMO/ABSTRACT/RESUMEN/... y los preserva VERBATIM, cada
uno etiquetado con su idioma, sin traducir ni fusionar. Portado y consolidado
desde el piloto (extract_abstracts.py), aquí como función pura del dominio.
"""

from __future__ import annotations

import re

from .classify import language_scores
from .contract import Abstract

# Encabezados de bloque de resumen -> idioma.
_HEADERS = [
    ("RESUMO", "pt"),
    ("ABSTRACT", "en"),
    ("RESUMEN", "es"),
    ("RÉSUMÉ", "fr"),
    ("RESUME", "fr"),
    ("RIASSUNTO", "it"),
    ("ZUSAMMENFASSUNG", "de"),
]
_HEADER_TO_LANG = {h.upper(): lg for h, lg in _HEADERS}

# El header ocupa la línea o lleva un separador antes del texto en esa línea.
# El whitespace no cruza saltos de línea ni permite prefijos como RESUMOS.
_HEADER_RE = re.compile(
    r"(?im)^[^\S\r\n]*("
    + "|".join(re.escape(h) for h, _ in _HEADERS)
    + r")(?!\w)[^\S\r\n]*(?:[:.\-–—](?=\s|$)[^\S\r\n]*|(?=\r?$))"
)
_KW_RE = re.compile(
    r"(?i)\b("
    r"Palavras?[-\s]*chaves?|"
    r"Palabras?[-\s]*llaves?|"
    r"Palabras?\s*claves?|"
    r"Key[-\s]*words?|"
    r"Mots?[-\s]*cl[ée]s|"
    r"Descritores?|"
    r"Descriptors?"
    r")\b\s*[:.\-]?\s*"
)
_BODY_START_RE = re.compile(
    r"(?im)^\s*(Introdu[cç][aã]o|Introduction|Introducci[oó]n|"
    r"1\.?\s+Introdu|Background)\b"
)
_CUT_TAIL = [
    r"(?i)\bCom\.\s*Ci[eê]ncias\s+Sa[uú]de\b",
    r"(?i)\bRev\.?\s*[A-Z][a-z]+\.?\s*\d{4}",
    r"(?i)\bTelefone\b",
    r"(?i)\bE[- ]?mail\b",
    r"(?i)\bEndere[cç]o\b",
    r"(?i)\bPalabras[- ]llave\b",
]

_MIN_BODY = 40
_MAX_BODY = 2500


# Encabezados ambiguos que también pueden aparecer como palabras normales.
_AMBIGUOUS_HEADERS = {"RESUME"}

# Ventana usada para buscar palabras clave después de un encabezado ambiguo.
_AMBIGUOUS_CONTEXT_WINDOW = 3500


def _first_body_start(text: str) -> int | None:
    """Devuelve la posición probable donde comienza el cuerpo principal."""
    match = _BODY_START_RE.search(text)
    return match.start() if match else None


def _line_tail(text: str, match: re.Match[str]) -> str:
    """Devuelve el contenido restante de la línea después del encabezado."""
    line_end = text.find("\n", match.end())

    if line_end == -1:
        line_end = len(text)

    return text[match.end() : line_end].strip()


def _is_valid_ambiguous_header(
    text: str,
    match: re.Match[str],
    body_start: int | None,
) -> bool:
    """Valida encabezados ambiguos como RESUME usando contexto estructural."""
    # Si aparece después de la introducción, casi seguro pertenece al cuerpo.
    if body_start is not None and match.start() > body_start:
        return False

    tail = _line_tail(text, match)

    # Ejemplo de falso positivo causado por salto de línea:
    #
    #   la estrategia se
    #   resume à reorganización...
    #
    # Después de RESUME continúa una frase en minúscula.
    if tail and tail[0].islower():
        return False

    context_end = min(
        len(text),
        match.end() + _AMBIGUOUS_CONTEXT_WINDOW,
    )
    context = text[match.end() : context_end]

    # RESUME sin acento solo se acepta si existe una señal estructural
    # adicional típica de un resumen, como Mots-clés o Keywords.
    return bool(_KW_RE.search(context))


def _find_abstract_headers(text: str) -> list[re.Match[str]]:
    """Devuelve solamente encabezados compatibles con bloques de resumen."""
    candidates = list(_HEADER_RE.finditer(text))

    if not candidates:
        return []

    body_start = _first_body_start(text)

    matches: list[re.Match[str]] = []

    for match in candidates:
        header = match.group(1).upper()

        if (header in _AMBIGUOUS_HEADERS) and (
            not _is_valid_ambiguous_header(text, match, body_start)
        ):
            continue

        matches.append(match)

    return matches


def article_body_ranges(text: str) -> list[tuple[int, int]]:
    """Identifica introducciones aisladas, salvo resúmenes estructurados."""
    headers = _find_abstract_headers(text)
    ranges = []
    for match in re.finditer(
        r"(?im)^[^\S\n]*(?:INTRODUÇÃO|INTRODUCTION|INTRODUCCIÓN|BACKGROUND)[^\S\n]*$",
        text,
    ):
        stop = next((h.start() for h in headers if h.start() > match.end()), len(text))
        following = text[match.end() : stop]
        keyword = _KW_RE.search(following)
        structured = re.search(
            r"(?im)^\s*(?:Methods|Métodos|Metodolog[íi]a|Méthodes|Metodi|Methoden)\s*:",
            following[: keyword.start() if keyword else 2500],
        )
        preceding = next(
            (h.end() for h in reversed(headers) if h.end() <= match.start()), 0
        )
        prefix = text[preceding : match.start()]
        if not structured or _KW_RE.search(prefix) or suspicious_candidate(prefix):
            ranges.append((match.start(), stop))
    return ranges


def suspicious_candidate(text: str) -> bool:
    """Marca contaminación editorial inequívoca; no certifica los demás casos."""
    return bool(
        re.search(
            r"(?i)^\s*(?:\d{1,4}\s+)?(?:original paper|artigo original|artículo original)\b|"
            r"\b\d{4}\s*;\s*\d+\s*\(|"
            r"\b(?:doi|issn)\s*:",
            text,
        )
    )


def abstract_evidence(text: str) -> list[dict]:
    """Señala bloques previos a palabras clave; no extrae ni certifica resúmenes."""
    headers = _find_abstract_headers(text)
    body_start = min((a for a, _ in article_body_ranges(text)), default=len(text))
    evidence = []
    for marker in _KW_RE.finditer(text):
        line_start = text.rfind("\n", 0, marker.start()) + 1
        if text[line_start : marker.start()].strip() or marker.start() >= body_start:
            continue
        label = marker.group(1).casefold()
        lang = (
            "en"
            if label.startswith("key")
            else "pt"
            if label.startswith(("palavra", "descritor"))
            else "es"
            if label.startswith("palabra")
            else "fr"
            if label.startswith("mot")
            else ""
        )
        if not lang or not any(
            _HEADER_TO_LANG[h.group(1).upper()] == lang for h in headers
        ):
            continue
        end = len(text[:line_start].rstrip())
        # Un bloque inmediato y acotado evita arrastrar títulos y otras secciones.
        boundaries = [m.end() for m in re.finditer(r"\n[ \t]*\n", text[:end])]
        boundaries.extend(h.end() for h in headers if h.end() <= end)
        start = max(boundaries, default=0)
        while start < end and text[start].isspace():
            start += 1
        block = text[start:end]
        words = re.findall(r"\b[^\W\d_]+\b", block)
        scores = language_scores(block)
        if (
            not 40 <= len(block) <= 6000
            or len(words) < 8
            or not re.search(r"[.!?]$", block)
            or suspicious_candidate(block)
            or _KW_RE.search(block)
            or not scores
            or scores.get(lang, 0) < 10
            or any(
                score >= scores[lang]
                for other, score in scores.items()
                if other != lang
            )
        ):
            continue
        evidence.append({"lang": lang, "span_start": start, "span_end": end})
    return evidence


def extract_abstracts(text: str) -> list[Abstract]:
    """Devuelve bloques de resumen de origen verbatim (lista vacía si no hay)."""
    matches = _find_abstract_headers(text)
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
            kw = re.split(r"\n\s*\n", chunk[kwm.end() :].strip())[0].strip()
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
