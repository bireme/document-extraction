"""Routing de OCR por confianza (DOMINIO PURO).

Replica la decisión validada en el piloto: usar Tesseract cuando su confianza
media es alta y hay suficientes palabras; si no, escalar al VLM. Aquí solo vive
la DECISIÓN y el parseo de la confianza; la ejecución (Tesseract/VLM) es de los
adaptadores.
"""

from __future__ import annotations

import csv
import io

# Umbrales del piloto.
MIN_CONF = 75.0
MIN_WORDS = 15


def route_page(
    conf: float, words: int, min_conf: float = MIN_CONF, min_words: int = MIN_WORDS
) -> str:
    """Devuelve 'tesseract' si la confianza es alta; si no, 'vlm'."""
    if conf >= min_conf and words >= min_words:
        return "tesseract"
    return "vlm"


def parse_tsv_confidence(tsv: str) -> tuple[float, int]:
    """Confianza media y nº de palabras desde el TSV de Tesseract.

    Ignora filas con conf < 0 o texto vacío (líneas de estructura).
    """
    confs: list[float] = []
    words = 0
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        try:
            c = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            continue
        if c >= 0 and (row.get("text") or "").strip():
            confs.append(c)
            words += 1
    avg = sum(confs) / len(confs) if confs else 0.0
    return avg, words


def parse_tsv_words(tsv: str) -> list[str]:
    """Palabras que Tesseract leyó (filas con conf >= 0 y texto).

    FASE19: base de contraste léxico para verificar la salida del VLM,
    sin OCR adicional.
    """
    out: list[str] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        try:
            c = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            continue
        word = (row.get("text") or "").strip()
        if c >= 0 and word:
            out.append(word)
    return out


def parse_tsv_lines(tsv: str) -> str:
    """Reconstruye el texto Tesseract del TSV agrupando por línea.

    FASE19: texto de degradación cuando el VLM se rechaza (ya existe del
    routing; no requiere re-ejecutar Tesseract).
    """
    lines: dict[tuple, list[str]] = {}
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        try:
            c = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            continue
        word = (row.get("text") or "").strip()
        if c < 0 or not word:
            continue
        try:
            key = (
                int(row.get("block_num") or 0),
                int(row.get("par_num") or 0),
                int(row.get("line_num") or 0),
            )
        except (TypeError, ValueError):
            key = (0, 0, 0)
        lines.setdefault(key, []).append(word)
    return "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
