"""Extracción de metadata embebida del PDF (adaptador, capa externa).

Lee el document-info del PDF vía `pdfinfo` (poppler-utils, requisito duro
ya existente del proyecto) y lo normaliza a un dict plano para el dominio
(bibframe.merge_bib_sources). Tolerante a fallos: binario ausente, PDF
corrupto, timeout o campos vacíos -> dict vacío o parcial, nunca lanza.
"""

from __future__ import annotations

import subprocess

# Campos de pdfinfo -> clave normalizada del dict resultado.
_FIELDS = {
    "Title": "title",
    "Subject": "subject",
    "Author": "author",
    "Keywords": "keywords",
    "CreationDate": "creation_date",
    "Pages": "pages",
}


def read_pdf_info(path: str, timeout: int = 15) -> dict:
    """Metadata embebida del PDF como dict normalizado (posiblemente vacío).

    Claves: title, subject, author, keywords, creation_date, pages.
    Solo incluye claves con valor no vacío.
    """
    try:
        proc = subprocess.run(
            ["pdfinfo", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0:
        return {}

    out: dict = {}
    for line in proc.stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        norm = _FIELDS.get(key.strip())
        if not norm:
            continue
        value = value.strip()
        if not value:
            continue
        if norm == "pages":
            try:
                out[norm] = int(value)
            except ValueError:
                continue
        else:
            out[norm] = value
    return out
