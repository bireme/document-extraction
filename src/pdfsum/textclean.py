"""Limpieza del transcript para el resumidor (DOMINIO PURO, FASE17).

El transcript persistido en ocr/<doc_id>.txt queda CRUDO (fidelidad
verbatim, auditable); esta limpieza se aplica EN MEMORIA antes de
clasificar/extraer/resumir, y puede evolucionar sin invalidar cachés:

  - Des-hifenización de cortes de línea ("informa-\\nción" -> "información";
    "Guinea-\\nBissau" conserva el guion).
  - Encabezados/pies repetidos: líneas cuya forma normalizada se repite en
    >= 40% de las páginas (mín. 3) en los bordes de página.
  - Líneas que son solo número de página (dígitos o romanos).

Requiere fronteras de página: form-feed (\\f, pdftotext nativo) o marcadores
"=== pág N ===" (OCR/mixto). Sin fronteras, solo des-hifenización.
"""

from __future__ import annotations

import re

# Línea repetida en >= este ratio de páginas (y >= _MIN_PAGES) = encabezado/pie.
HEADER_REPEAT_RATIO = 0.4
_MIN_PAGES = 3
# Zona de borde de página donde puede vivir un encabezado/pie (nº de líneas).
_EDGE_LINES = 3

_PAGE_MARKER = re.compile(r"(?m)^=== pág \d+ ===$")
# guion al final de línea entre letra y letra minúscula -> unir sin guion
_HYPHEN_LOWER = re.compile(r"(\w)-\n(\s*)([a-záàâãéêíóôõúüçñèìòù])")
# guion al final de línea con continuación en mayúscula -> conservar guion
_HYPHEN_UPPER = re.compile(r"(\w)-\n(\s*)([A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇÑ0-9])")
_PAGENUM = re.compile(r"(?i)^\s*(\d{1,4}|[ivxlcdm]{1,7})\s*$")


def dehyphenate(text: str) -> str:
    """Une palabras cortadas por salto de línea. Idempotente."""
    text = _HYPHEN_LOWER.sub(r"\1\3", text)
    text = _HYPHEN_UPPER.sub(r"\1-\3", text)
    return text


def split_pages(text: str) -> tuple[list[str], str] | None:
    """Divide en páginas si hay fronteras detectables.

    Devuelve (páginas, tipo_frontera) con tipo 'formfeed' | 'marker',
    o None si no hay fronteras (la limpieza por página no aplica).
    """
    if "\f" in text:
        return text.split("\f"), "formfeed"
    if len(_PAGE_MARKER.findall(text)) >= 2:
        # conservar los marcadores: dividir DESPUÉS de cada marcador
        parts = re.split(r"(?m)^(=== pág \d+ ===)$\n?", text)
        # parts = [pre, marker, body, marker, body, ...]
        pages = []
        for i in range(1, len(parts), 2):
            body = parts[i + 1] if i + 1 < len(parts) else ""
            pages.append(parts[i] + "\n" + body)
        return pages, "marker"
    return None


def _normalize_line(line: str) -> str:
    """Forma canónica para detectar repetición.

    Ignora SOLO los dígitos en los extremos de la línea (nº de página de
    encabezados/pies reales); los dígitos interiores se conservan para no
    confundir contenido distinto que solo varía en una cifra.
    """
    line = re.sub(r"^[\s\d]+|[\s\d]+$", "", line)
    return re.sub(r"\s+", " ", line).lower()


def _edge_lines(lines: list[str], skip_marker: bool) -> list[int]:
    """Índices de las líneas de borde (primeras/últimas no vacías)."""
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    if skip_marker and idx and _PAGE_MARKER.match(lines[idx[0]]):
        idx = idx[1:]
    return idx[:_EDGE_LINES] + idx[-_EDGE_LINES:]


def _repeated_edges(pages_lines: list[list[str]], marker: bool) -> set[str]:
    """Formas normalizadas que se repiten en bordes de >= 40% de páginas."""
    if len(pages_lines) < _MIN_PAGES:
        return set()
    counts: dict[str, int] = {}
    for lines in pages_lines:
        seen: set[str] = set()
        for i in _edge_lines(lines, marker):
            norm = _normalize_line(lines[i])
            if norm and norm not in seen:
                seen.add(norm)
                counts[norm] = counts.get(norm, 0) + 1
    minimum = max(_MIN_PAGES, int(HEADER_REPEAT_RATIO * len(pages_lines)))
    return {norm for norm, n in counts.items() if n >= minimum}


def remove_headers_footers(text: str) -> str:
    """Elimina encabezados/pies repetidos y líneas solo-número de página."""
    split = split_pages(text)
    if split is None:
        return text
    pages, kind = split
    marker = kind == "marker"
    pages_lines = [p.split("\n") for p in pages]
    repeated = _repeated_edges(pages_lines, marker)

    out_pages: list[str] = []
    for lines in pages_lines:
        edges = set(_edge_lines(lines, marker))
        kept = []
        for i, line in enumerate(lines):
            if i in edges:
                if _normalize_line(line) in repeated:
                    continue
                if _PAGENUM.match(line):
                    continue
            kept.append(line)
        out_pages.append("\n".join(kept))
    sep = "\f" if kind == "formfeed" else "\n"
    return sep.join(out_pages)


def clean_text(text: str) -> str:
    """Limpieza completa: encabezados/pies + números + des-hifenización."""
    return dehyphenate(remove_headers_footers(text))
