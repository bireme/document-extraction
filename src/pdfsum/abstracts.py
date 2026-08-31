"""Extracción de resúmenes de origen multilingües (DOMINIO PURO).

Localiza bloques RESUMO/ABSTRACT/RESUMEN/... y los preserva VERBATIM, cada
uno etiquetado con su idioma, sin traducir ni fusionar.

Los encabezados ambiguos, como RESUME sin acentos, requieren validación
estructural adicional para evitar falsos positivos dentro del cuerpo del texto.
"""

from __future__ import annotations

import re

from .contract import Abstract


# Encabezados de bloque de resumen -> idioma.
_HEADERS = [
    ("RESUMO", "pt"),
    ("ABSTRACT", "en"),
    ("SUMMARY", "en"),
    ("RESUMEN", "es"),
    ("RÉSUMÉ", "fr"),
    ("RESUME", "fr"),
    ("RIASSUNTO", "it"),
    ("ZUSAMMENFASSUNG", "de"),
]

_HEADER_TO_LANG = {h.upper(): lg for h, lg in _HEADERS}

# Encabezados ambiguos que también pueden aparecer como palabras normales.
_AMBIGUOUS_HEADERS = {"RESUME"}

_HEADER_RE = re.compile(
    r"(?im)^\s*("
    + "|".join(re.escape(h) for h, _ in _HEADERS)
    + r")\s*[:.\-]?\s*"
)

_KW_RE = re.compile(
    r"(?i)\b("
    r"Palavras[- ]chave|"
    r"Palabras[- ]llave|"
    r"Palabras\s+clave|"
    r"Keywords?|"
    r"Mots[- ]cl[ée]s|"
    r"Descritores|"
    r"Descriptors"
    r")\b\s*[:.\-]?\s*"
)

_BODY_START_RE = re.compile(
    r"(?im)^\s*("
    r"Introdu[cç][aã]o|"
    r"Introduction|"
    r"Introducci[oó]n|"
    r"1\.?\s+Introdu|"
    r"Background"
    r")\b"
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
    if not _KW_RE.search(context):
        return False

    return True


def _find_abstract_headers(text: str) -> list[re.Match[str]]:
    """Devuelve solamente encabezados compatibles con bloques de resumen."""
    candidates = list(_HEADER_RE.finditer(text))

    if not candidates:
        return []

    body_start = _first_body_start(text)

    matches: list[re.Match[str]] = []

    for match in candidates:
        header = match.group(1).upper()

        if header in _AMBIGUOUS_HEADERS:
            if not _is_valid_ambiguous_header(
                text,
                match,
                body_start,
            ):
                continue

        matches.append(match)

    return matches


def extract_abstracts(text: str) -> list[Abstract]:
    """Devuelve bloques de resumen de origen verbatim (lista vacía si no hay)."""
    matches = _find_abstract_headers(text)
    out: list[Abstract] = []

    for i, match in enumerate(matches):
        header = match.group(1).upper()
        lang = _HEADER_TO_LANG[header]

        start = match.end()

        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(text)

        chunk = text[start:end].strip()

        kw = ""
        kwm = _KW_RE.search(chunk)

        if kwm:
            body = chunk[: kwm.start()].strip()
            kw = re.split(
                r"\n\s*\n",
                chunk[kwm.end() :].strip(),
            )[0].strip()
        else:
            body = chunk

        bs = _BODY_START_RE.search(body)

        if bs and bs.start() > 200:
            body = body[: bs.start()].strip()

        body = re.sub(
            r"\s+",
            " ",
            " ".join(body.split("\n")),
        ).strip()

        for pattern in _CUT_TAIL:
            body = re.split(pattern, body)[0].strip()

        if len(body) > _MAX_BODY:
            truncated = body[:_MAX_BODY]

            if "." in truncated:
                truncated = truncated.rsplit(".", 1)[0].strip()

            body = truncated.rstrip() + "."

        if len(body) < _MIN_BODY:
            continue

        out.append(
            Abstract(
                lang=lang,
                header=header,
                text=body,
                keywords=kw,
            )
        )

    return out


def abstract_langs(abstracts: list[Abstract]) -> list[str]:
    """Idiomas presentes, en orden de aparición y sin duplicados."""
    seen: list[str] = []

    for abstract in abstracts:
        if abstract.lang not in seen:
            seen.append(abstract.lang)

    return seen
