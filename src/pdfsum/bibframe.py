"""Datos bibliográficos + registro BIBFRAME JSON-LD (DOMINIO PURO).

Combina dos fuentes de datos bibliográficos por documento:
  1. Metadata embebida del PDF (dict de adapters/pdf_metadata.py) —
     explícita, tiene PRECEDENCIA.
  2. El resumen ya generado (SummaryResult) — complementa lo que falte
     (título de sección, entidad, términos candidatos, idioma, páginas).

Política de dato mínimo: sin TÍTULO (de cualquiera de las fuentes) no se
emite registro. El registro producido es un BORRADOR para revisión humana
(mismo criterio que export.py/LILACS): no se inventan datos, solo se
mapean los disponibles dejando constancia de la fuente de cada campo.

Salida: BIBFRAME 2.x en JSON-LD (vocabulario id.loc.gov/ontologies/
bibframe), un par Work + Instance enlazados por bf:instanceOf. Un registro
por documento/PDF (doc_id trazable en los @id y en _pdfsum).

Este módulo es DOMINIO: no ejecuta procesos, no hace IO ni red.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contract import SummaryResult

BIBFRAME_CONTEXT = {
    "bf": "http://id.loc.gov/ontologies/bibframe/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
}

# idioma_principal del resumen -> código LOC (id.loc.gov/vocabulary/languages)
_LOC_LANG = {"es": "spa", "pt": "por", "en": "eng", "fr": "fre"}

# Clave de sección con términos candidatos, por plantilla (igual que export.py).
_TERMS_KEY = {"A": "palabras_clave", "B": "terminos", "C": "terminos"}

_DRAFT_NOTE = (
    "Borrador para revisión humana. Campos mapeados desde la metadata "
    "embebida del PDF y/o el resumen generado (ver sources); no validados "
    "contra autoridades (VIAF/DeCS/MeSH)."
)


@dataclass
class BibData:
    """Datos bibliográficos canónicos de UN documento, con procedencia."""

    doc_id: str
    title: str = ""
    section_title: str = ""  # Subject del PDF (capítulo) o título del resumen
    authors: list[str] = field(default_factory=list)
    publisher: str = ""
    date: str = ""  # año (YYYY) si se pudo derivar
    language: str = ""  # código interno (es/pt/en/...)
    pages: int = 0
    subjects: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)  # campo -> fuente


def _split_authors(raw: str) -> list[str]:
    """Divide una cadena de autores en nombres individuales (heurística)."""
    if not raw.strip():
        return []
    parts = re.split(r"\s*(?:;|/|\by\b|\be\b|\band\b)\s*", raw)
    return [p.strip(" .,") for p in parts if p.strip(" .,")]


def _year(raw: str) -> str:
    """Extrae un año (4 dígitos razonables) de una fecha cruda de pdfinfo."""
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", raw)
    return m.group(1) if m else ""


def _summary_terms(summary: SummaryResult) -> list[str]:
    key = _TERMS_KEY.get(summary.plantilla, "terminos")
    raw = summary.secciones.get(key, "")
    terms = []
    for line in raw.splitlines():
        t = line.strip().lstrip("-•*").strip(" .,")
        if t:
            terms.append(t)
    return terms


def merge_bib_sources(pdf_meta: dict | None, summary: SummaryResult) -> BibData:
    """Combina metadata del PDF (precedencia) con el resumen (complemento).

    `pdf_meta` es el dict normalizado de adapters/pdf_metadata.py (o None
    si el PDF no está disponible). Cada campo poblado registra su fuente
    en `sources` ('pdf_metadata' | 'summary').
    """
    pdf_meta = pdf_meta or {}
    bib = BibData(doc_id=summary.doc_id)

    def _set(fieldname: str, pdf_value, summary_value) -> None:
        if pdf_value:
            setattr(bib, fieldname, pdf_value)
            bib.sources[fieldname] = "pdf_metadata"
        elif summary_value:
            setattr(bib, fieldname, summary_value)
            bib.sources[fieldname] = "summary"

    _set(
        "title",
        (pdf_meta.get("title") or "").strip(),
        summary.secciones.get("titulo", "").strip(),
    )
    # Subject del PDF suele ser el capítulo; si el título vino del PDF y
    # además hay título de resumen distinto, este último es el del capítulo.
    summary_title = summary.secciones.get("titulo", "").strip()
    pdf_subject = (pdf_meta.get("subject") or "").strip()
    section = pdf_subject or (
        summary_title if bib.sources.get("title") == "pdf_metadata" else ""
    )
    if section and section != bib.title:
        bib.section_title = section
        bib.sources["section_title"] = "pdf_metadata" if pdf_subject else "summary"

    _set(
        "authors",
        _split_authors(pdf_meta.get("author") or ""),
        _split_authors(summary.secciones.get("autores", "")),
    )
    _set(
        "publisher",
        "",  # pdfinfo no trae editorial confiable (Producer es software)
        summary.secciones.get("entidad", "").strip(),
    )
    if bib.publisher.lower().startswith("no se"):
        # el resumidor a veces responde "No se especifica..." — no es dato
        bib.publisher = ""
        bib.sources.pop("publisher", None)
    _set("date", _year(pdf_meta.get("creation_date") or ""), "")
    _set("language", "", summary.idioma_principal)
    _set(
        "pages",
        int(pdf_meta.get("pages") or 0),
        int(summary.meta.get("pages") or 0),
    )
    kw = _split_authors(pdf_meta.get("keywords") or "")  # split genérico
    _set("subjects", kw, _summary_terms(summary))
    return bib


def has_minimum_data(bib: BibData) -> bool:
    """Dato mínimo para emitir registro: título no vacío."""
    return bool(bib.title.strip())


def to_bibframe(bib: BibData) -> dict:
    """Mapea BibData a un registro BIBFRAME 2.x JSON-LD (Work + Instance)."""
    work_id = f"urn:pdfsum:work:{bib.doc_id}"
    instance_id = f"urn:pdfsum:instance:{bib.doc_id}"

    work: dict = {
        "@id": work_id,
        "@type": "bf:Work",
        "bf:title": {"@type": "bf:Title", "bf:mainTitle": bib.title},
    }
    if bib.language and bib.language in _LOC_LANG:
        work["bf:language"] = {
            "@id": f"http://id.loc.gov/vocabulary/languages/{_LOC_LANG[bib.language]}"
        }
    if bib.authors:
        work["bf:contribution"] = [
            {
                "@type": "bf:Contribution",
                "bf:agent": {"@type": "bf:Agent", "rdfs:label": a},
            }
            for a in bib.authors
        ]
    if bib.subjects:
        work["bf:subject"] = [
            {"@type": "bf:Topic", "rdfs:label": s} for s in bib.subjects
        ]

    instance: dict = {
        "@id": instance_id,
        "@type": "bf:Instance",
        "bf:instanceOf": {"@id": work_id},
    }
    if bib.section_title:
        instance["bf:title"] = {
            "@type": "bf:Title",
            "bf:mainTitle": bib.section_title,
        }
    if bib.pages:
        instance["bf:extent"] = {
            "@type": "bf:Extent",
            "rdfs:label": f"{bib.pages} páginas",
        }
    if bib.publisher or bib.date:
        prov: dict = {"@type": "bf:Publication"}
        if bib.publisher:
            prov["bf:agent"] = {
                "@type": "bf:Agent",
                "rdfs:label": bib.publisher,
            }
        if bib.date:
            prov["bf:date"] = bib.date
        instance["bf:provisionActivity"] = prov

    return {
        "@context": dict(BIBFRAME_CONTEXT),
        "@graph": [work, instance],
        "_pdfsum": {
            "status": "draft",
            "doc_id": bib.doc_id,
            "sources": dict(bib.sources),
            "note": _DRAFT_NOTE,
        },
    }
