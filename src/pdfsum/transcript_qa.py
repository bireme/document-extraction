"""QA de transcripción: gates de calidad del TRANSCRIPT (DOMINIO PURO).

FASE16: la calidad del OCR se calculaba y se descartaba; estos gates hacen
medible el transcript ANTES de resumir (garbage in -> garbage out). Validan
texto + meta opcional de transcripción, sin IO ni procesos externos.

Gates:
  - garbage:       ratio de caracteres fuera del alfabeto esperado (error).
  - stopword_ratio: señal de idioma baja -> texto posiblemente ilegible
                    (warning; reutiliza classify.language_scores).
  - paginas:       páginas vacías según meta (warning; error si supera ratio).
  - conf_baja:     confianza OCR media < umbral (warning).
  - legacy_cache:  transcript de caché legacy sin métricas (warning).

Umbrales calibrados sobre el set de control del repo (samples/pdfs +
corpus ECIMED): ajustables por parámetro, nunca hardcodeados en el caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .classify import language_scores

# --- Umbrales por defecto (calibrados en C7 del eval-spec FASE16) ----------
# Ratio máximo de caracteres fuera del alfabeto esperado. Los transcripts
# legibles del set de control quedan < 0.05; OCR basura supera 0.25.
GARBAGE_MAX_RATIO = 0.15
# Score mínimo de stopwords del mejor idioma (language_scores devuelve %).
# Textos legibles pt/es/en del corpus puntúan > 10; ruido OCR queda < 2.
STOPWORD_MIN_SCORE = 2.0
# Mínimo de tokens para juzgar idioma/garbage (evitar falsos positivos).
MIN_TOKENS = 40
# Confianza Tesseract media mínima (misma escala 0-100 que ocr_routing).
CONF_MIN = 60.0
# Ratio de páginas vacías que escala el gate de warning a error.
EMPTY_PAGES_ERROR_RATIO = 0.2

# Alfabeto esperado: letras latinas (con diacríticos), dígitos, puntuación
# habitual y espacio. Todo lo demás cuenta como "basura" de OCR.
_ALLOWED = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž0-9\s"
    r".,;:¡!¿?()\[\]{}<>\"'´`’‘“”«»\-–—_/\\%&@#*+=§°ºª·•€$£~^|]"
)

# Marcador de página que emite el transcriptor híbrido ("=== pág N ===").
_PAGE_MARKER = re.compile(r"(?m)^=== pág \d+ ===$")


@dataclass
class TranscriptGateFailure:
    gate: str
    detail: str
    severity: str = "error"


@dataclass
class TranscriptQAReport:
    doc_id: str
    failures: list[TranscriptGateFailure] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        return not any(f.severity == "error" for f in self.failures)

    def add(self, gate: str, detail: str, severity: str = "error") -> None:
        self.failures.append(TranscriptGateFailure(gate, detail, severity))

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "passed": self.is_ok,
            "failures": [
                {"gate": f.gate, "detail": f.detail, "severity": f.severity}
                for f in self.failures
            ],
        }


def garbage_ratio(text: str) -> float:
    """Proporción de caracteres fuera del alfabeto esperado (0.0-1.0)."""
    stripped = _PAGE_MARKER.sub("", text)
    if not stripped.strip():
        return 0.0
    total = len(stripped)
    allowed = len(_ALLOWED.findall(stripped))
    return (total - allowed) / total


def _gate_garbage(text: str, rep: TranscriptQAReport, max_ratio: float) -> None:
    if len(text.split()) < MIN_TOKENS:
        return
    ratio = garbage_ratio(text)
    if ratio > max_ratio:
        rep.add(
            "garbage",
            f"ratio de caracteres basura {ratio:.3f} > {max_ratio}",
        )


def _gate_stopwords(text: str, rep: TranscriptQAReport, min_score: float) -> None:
    if len(text.split()) < MIN_TOKENS:
        return
    scores = language_scores(text)
    best = max(scores.values()) if scores else 0.0
    if best < min_score:
        rep.add(
            "stopword_ratio",
            f"señal de idioma {best:.2f} < {min_score} (texto posiblemente ilegible)",
            severity="warning",
        )


def _gate_pages(meta: dict, rep: TranscriptQAReport, error_ratio: float) -> None:
    detail = meta.get("pages_detail") or []
    with_chars = [p for p in detail if "chars" in p]
    if not with_chars:
        return
    empty = [p["page"] for p in with_chars if not p.get("chars")]
    if not empty:
        return
    ratio = len(empty) / len(with_chars)
    severity = "error" if ratio > error_ratio else "warning"
    rep.add(
        "paginas",
        f"{len(empty)}/{len(with_chars)} páginas sin texto: {empty[:10]}",
        severity=severity,
    )


def _gate_confidence(meta: dict, rep: TranscriptQAReport, min_conf: float) -> None:
    conf = (meta.get("quality") or {}).get("conf_media")
    if conf is None:
        return
    if conf < min_conf:
        rep.add(
            "conf_baja",
            f"confianza OCR media {conf:.1f} < {min_conf}",
            severity="warning",
        )


def _gate_legacy(meta: dict, rep: TranscriptQAReport) -> None:
    if meta.get("legacy"):
        rep.add(
            "legacy_cache",
            "transcript de caché legacy (sin métricas de OCR persistidas); "
            "usar --retranscribe para regenerar con métricas",
            severity="warning",
        )


def check_transcript(
    text: str,
    meta: dict | None = None,
    *,
    doc_id: str = "",
    garbage_max_ratio: float = GARBAGE_MAX_RATIO,
    stopword_min_score: float = STOPWORD_MIN_SCORE,
    conf_min: float = CONF_MIN,
    empty_pages_error_ratio: float = EMPTY_PAGES_ERROR_RATIO,
) -> TranscriptQAReport:
    """Aplica los gates de transcript. `meta` es opcional (gates de texto
    funcionan solos); con meta se añaden páginas/confianza/legacy."""
    rep = TranscriptQAReport(doc_id=doc_id)
    _gate_garbage(text, rep, garbage_max_ratio)
    _gate_stopwords(text, rep, stopword_min_score)
    if meta:
        _gate_pages(meta, rep, empty_pages_error_ratio)
        _gate_confidence(meta, rep, conf_min)
        _gate_legacy(meta, rep)
    return rep
