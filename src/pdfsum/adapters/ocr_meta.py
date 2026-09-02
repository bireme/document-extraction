"""Meta de transcripción persistida + caché versionada (adaptador, FASE16).

Escribe/lee `ocr/<doc_id>.meta.json` junto a cada transcript y decide si la
caché es reutilizable: solo si el sha256 del PDF y la versión del pipeline
OCR coinciden. Cachés LEGACY (txt sin meta) se reutilizan sin re-OCR masivo,
generando meta mínima `{"legacy": true}` (gate warning en transcript_qa).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..contract import TranscriptResult

META_VERSION = "1.0"
# Subir cuando cambie el comportamiento del pipeline de transcripción:
# invalida cachés generadas con versiones anteriores para que las mejoras
# de OCR lleguen a corpus ya procesados.
# "2" = FASE17: decisión nativo/OCR por página (los documentos mixtos
# recuperan las páginas escaneadas que antes se perdían en silencio).
OCR_PIPELINE_VERSION = "2"

_PAGE_MARKER = re.compile(r"(?m)^=== pág \d+ ===$")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def meta_path(ocr_file: Path) -> Path:
    return ocr_file.with_suffix(".meta.json")


def _quality(pages_detail: list[dict] | None) -> dict:
    """Agregado de calidad a partir del detalle por página."""
    detail = pages_detail or []
    ocr_pages = [p for p in detail if p.get("conf") is not None]
    total_words = sum(p.get("words", 0) for p in ocr_pages)
    conf_media = (
        sum(p["conf"] * p.get("words", 0) for p in ocr_pages) / total_words
        if total_words
        else None
    )
    quality: dict = {
        "paginas_vlm": sum(1 for p in detail if p.get("source") == "vlm"),
        "paginas_vacias": sum(1 for p in detail if "chars" in p and not p.get("chars")),
    }
    if conf_media is not None:
        quality["conf_media"] = round(conf_media, 2)
    return quality


def build_meta(
    doc_id: str, pdf_path: str | Path, result: TranscriptResult, lang: str
) -> dict:
    return {
        "meta_version": META_VERSION,
        "ocr_pipeline_version": OCR_PIPELINE_VERSION,
        "doc_id": doc_id,
        "pdf_sha256": sha256_file(pdf_path),
        "pages": result.pages,
        "source_kind": result.source_kind.value,
        "lang_ocr": lang,
        "pages_detail": result.pages_detail or [],
        "quality": _quality(result.pages_detail),
    }


def infer_pages_from_text(text: str) -> int:
    """Páginas de un transcript LEGACY: cuenta marcadores '=== pág N ==='.

    Único lugar donde se infiere (antes duplicado ad-hoc en pdf_batch).
    """
    return len(_PAGE_MARKER.findall(text)) or 1


def build_legacy_meta(doc_id: str, pdf_path: str | Path, text: str) -> dict:
    """Meta mínima para caché previa a FASE16 (sin métricas de OCR)."""
    return {
        "meta_version": META_VERSION,
        "ocr_pipeline_version": None,
        "legacy": True,
        "doc_id": doc_id,
        "pdf_sha256": sha256_file(pdf_path),
        "pages": infer_pages_from_text(text),
        "source_kind": "cached",
        "pages_detail": [],
        "quality": {},
    }


def write_meta(ocr_file: Path, meta: dict) -> None:
    meta_path(ocr_file).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_meta(ocr_file: Path) -> dict | None:
    p = meta_path(ocr_file)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_valid(meta: dict | None, pdf_path: str | Path) -> bool:
    """Caché reutilizable sin re-OCR: mismo PDF y misma versión de pipeline.

    Meta legacy NO es 'válida' (el caller decide reutilizarla igualmente,
    con marca legacy, para no forzar re-OCR masivo de corpus existentes).
    """
    if not meta or meta.get("legacy"):
        return False
    return meta.get("ocr_pipeline_version") == OCR_PIPELINE_VERSION and meta.get(
        "pdf_sha256"
    ) == sha256_file(pdf_path)
