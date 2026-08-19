"""Clasificación determinista del documento (DOMINIO PURO).

Decide: origen (nativo/escaneado), idioma, y tipo de documento (que a su vez
determina la plantilla de resumen). Sin modelos ni procesos externos: solo
heurísticas sobre el texto ya extraído y metadatos simples.
"""
from __future__ import annotations

import re
import unicodedata

from .contract import TEMPLATE_BY_TYPE, DocType, SourceKind

# --- Origen: nativo vs escaneado ------------------------------------------
DEFAULT_TEXT_PER_PAGE_THRESHOLD = 100


def classify_source(
    text_chars: int, pages: int, threshold: int = DEFAULT_TEXT_PER_PAGE_THRESHOLD
) -> SourceKind:
    """NATIVO si hay >= threshold chars/página; si no ESCANEADO.

    (MIXTO se reserva para casos intermedios detectados aguas arriba; aquí la
    regla base es binaria por chars/página.)
    """
    if pages <= 0:
        return SourceKind.ESCANEADO
    per_page = text_chars / pages
    return SourceKind.NATIVO if per_page >= threshold else SourceKind.ESCANEADO


# --- Idioma: detector por stopwords (sin dependencias) --------------------
_STOP = {
    "pt": {"de", "que", "não", "uma", "com", "para", "como", "dos", "das",
           "por", "mais", "são", "também", "está", "pelo", "pela", "seu",
           "sua", "você", "então", "após", "é", "à", "às", "saúde", "doença"},
    "es": {"de", "que", "no", "una", "con", "para", "como", "los", "las",
           "por", "más", "son", "también", "está", "este", "esta", "su",
           "sus", "usted", "entonces", "después", "el", "la", "salud"},
    "en": {"the", "of", "and", "that", "with", "for", "from", "this", "are",
           "was", "which", "have", "has", "not", "their", "been", "between",
           "health", "disease", "study", "results", "objective", "methods"},
    "fr": {"de", "que", "ne", "une", "avec", "pour", "comme", "les", "des",
           "par", "plus", "sont", "aussi", "est", "cette", "leur", "vous",
           "alors", "après", "à", "santé", "maladie", "résultats"},
    "it": {"di", "che", "non", "una", "con", "per", "come", "gli", "dei",
           "delle", "più", "sono", "anche", "è", "questa", "loro", "dopo",
           "alla", "salute", "malattia", "risultati", "obiettivo"},
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-záàâãéêíóôõúüçñèìòùäöß]+", text.lower())


def language_scores(text: str) -> dict[str, float]:
    toks = _tokenize(unicodedata.normalize("NFC", text))
    if not toks:
        return {}
    total = len(toks)
    return {lang: 100 * sum(1 for w in toks if w in sw) / total
            for lang, sw in _STOP.items()}


def detect_language(text: str) -> str:
    scores = language_scores(text)
    if not scores:
        return "unknown"
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


# --- Tipo de documento -> plantilla ---------------------------------------
_IMRAD_MARKERS = re.compile(
    r"(?im)^\s*(RESUMO|ABSTRACT|RESUMEN|M[ÉE]TODOS?|METHODS?|"
    r"RESULTADOS?|RESULTS?|CONCLUS[ÕO]ES?|CONCLUSIONS?)\b"
)
_KEYWORDS_MARKERS = re.compile(
    r"(?i)\b(Palavras[- ]chave|Keywords?|Palabras\s+clave|Descritores)\b"
)
_TOC_MARKERS = re.compile(
    r"(?im)^\s*(SUM[ÁA]RIO|[ÍI]NDICE|TABLE OF CONTENTS|"
    r"PREF[ÁA]CIO|APRESENTA[ÇC][ÃA]O)\b"
)


# Un artículo científico rara vez supera este tamaño; por encima, con índice,
# es un manual/libro aunque contenga marcadores IMRAD en su interior.
ARTICLE_MAX_PAGES = 15


def classify_type(text: str, pages: int = 1) -> DocType:
    """Reconoce artículo / manual / divulgación por marcadores estructurales.

    Prioridad (lección del piloto con manuales largos que traen RESUMO/métodos
    en su interior y eran mal clasificados como artículo):
    - manual: tiene índice/sumário/prefácio Y es extenso (muchas páginas).
      Esto se evalúa ANTES que artículo para no confundir libros con papers.
    - articulo: marcadores IMRAD/abstract + keywords y tamaño de paper.
    - divulgacion: por defecto.
    """
    imrad_hits = len(_IMRAD_MARKERS.findall(text))
    has_keywords = bool(_KEYWORDS_MARKERS.search(text))
    has_toc = bool(_TOC_MARKERS.search(text))

    # Manual/libro: estructura de sumario/índice y documento extenso.
    if has_toc and pages >= 10:
        return DocType.MANUAL
    # Artículo: IMRAD + keywords, y con tamaño de paper (no un libro).
    if imrad_hits >= 2 and has_keywords and pages <= ARTICLE_MAX_PAGES:
        return DocType.ARTICULO
    return DocType.DIVULGACION


def template_for(doc_type: DocType) -> str:
    """Letra de plantilla (A/B/C) asociada al tipo (ver informe §3.1)."""
    return TEMPLATE_BY_TYPE[doc_type]
