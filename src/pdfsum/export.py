"""Export a formato de catalogación LILACS (DOMINIO PURO).

Mapea un SummaryResult a un registro con campos de la metodología LILACS
(BIREME). IMPORTANTE: produce un BORRADOR de registro para revisión humana,
NO un registro validado. En particular, los descriptores se exponen como
CANDIDATOS y requieren validación con el vocabulario DeCS/MeSH (no incluido).

Campos LILACS de referencia (Manual de Descrição Bibliográfica):
  05 tipo de documento, título, idioma, resumo, descritores.
Se usa un subconjunto pragmático y se anota su origen.
"""

from __future__ import annotations

from .contract import SummaryResult

# Mapa de tipo interno -> tipo de documento LILACS (campo 05, aproximado).
_LILACS_DOCTYPE = {
    "articulo": "S",  # artigo de periódico (Serial article)
    "manual": "M",  # monografia / manual
    "divulgacion": "M",  # material de divulgação -> monografía/no convencional
}

# Clave de sección que hace de "resumen" según la plantilla.
_SUMMARY_KEY = {
    "A": "objetivo",  # en artículo, el objetivo encabeza el abstract
    "B": "objeto_alcance",
    "C": "resumen_ejecutivo",
}
_TITLE_KEY = "titulo"
_TERMS_KEY = {"A": "palabras_clave", "B": "terminos", "C": "terminos"}


def _summary_text(res: SummaryResult) -> str:
    key = _SUMMARY_KEY.get(res.plantilla, "resumen_ejecutivo")
    return res.secciones.get(key, "").strip()


def _candidate_descriptors(res: SummaryResult) -> list[str]:
    key = _TERMS_KEY.get(res.plantilla, "terminos")
    raw = res.secciones.get(key, "")
    parts = [p.strip(" .;") for p in raw.replace(";", ",").split(",")]
    return [p for p in parts if p]


def to_lilacs(res: SummaryResult) -> dict:
    """Genera un registro LILACS borrador a partir del resumen.

    El registro incluye 'status: draft' y una nota explícita de que requiere
    validación humana (descriptores DeCS, tipo de documento, etc.).
    """
    doctype = _LILACS_DOCTYPE.get(res.tipo_documento, "M")
    # resúmenes por idioma: el ejecutivo + los abstracts de origen verbatim
    abstracts = [
        {
            "lang": res.idioma_principal,
            "text": _summary_text(res),
            "source": "generated",
        }
    ]
    for ab in res.abstracts_origem:
        abstracts.append({"lang": ab.lang, "text": ab.text, "source": "origin"})

    return {
        "status": "draft",
        "_note": (
            "Borrador para revisión humana. Los descriptores son "
            "CANDIDATOS y deben validarse con el vocabulario DeCS/MeSH. "
            "El tipo de documento LILACS es aproximado."
        ),
        "lilacs": {
            "05_tipo_documento": doctype,
            "titulo": res.secciones.get(_TITLE_KEY, "").strip(),
            "idioma_texto": res.idioma_principal,
            "resumos": abstracts,
            "descritores_candidatos": _candidate_descriptors(res),
            "idiomas_resumo_origem": res.idiomas_resumo_origem,
        },
        "origen": {
            "doc_id": res.doc_id,
            "tipo_interno": res.tipo_documento,
            "plantilla": res.plantilla,
            "contract_version": res.contract_version,
        },
    }
