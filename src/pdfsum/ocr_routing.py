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
