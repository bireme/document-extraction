"""Verificación de la salida del VLM (DOMINIO PURO, FASE19).

El fallback VLM era de confianza ciega: lo que devolviera el modelo de
visión entraba verbatim al transcript. Para una biblioteca médica una
alucinación insertada es peor que una página en blanco: nada la delata.

Checks (en orden): vacío, cháchara/descripción, solape léxico con las
palabras que Tesseract leyó en la misma región (base de contraste gratis,
del TSV del routing), idioma y explosión de longitud. Una salida ACEPTADA
entra al transcript sin modificar; la verificación nunca edita.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .classify import detect_language

# Umbral de solape calibrado en C5 del eval-spec FASE19 (0 falsos
# rechazos sobre las páginas VLM buenas del set de control BIREME).
OVERLAP_MIN = 0.30
# Mínimo de palabras útiles de Tesseract para juzgar solape.
MIN_BASE_WORDS = 5
# Longitud mínima de palabra para el contraste (evita ruido de 1-3 letras).
MIN_WORD_LEN = 4
# Texto VLM largo (tokens) para poder juzgar idioma.
LANG_MIN_TOKENS = 40
# Explosión: VLM enorme donde Tesseract vio casi nada.
EXPLOSION_CHARS = 3000
EXPLOSION_MAX_BASE = 10

# El modelo conversa o DESCRIBE la imagen en vez de transcribirla.
_CHATTER = [
    "a imagem mostra",
    "a imagem contém",
    "la imagen muestra",
    "esta imagen contiene",
    "the image shows",
    "the image contains",
    "this image depicts",
    "não posso",
    "no puedo",
    "i cannot",
    "i can't",
    "i'm sorry",
    "lo siento",
    "desculpe",
    "as an ai",
    "?como puedo ayudar",
    "como posso ajudar",
]

# Pack Tesseract -> código de idioma del detector del dominio.
_PACK2LANG = {
    "por": "pt",
    "spa": "es",
    "eng": "en",
    "fra": "fr",
    "ita": "it",
}


@dataclass
class VlmVerdict:
    accepted: bool
    reason: str | None = None


def _fold(word: str) -> str:
    """Minúsculas y sin acentos (contraste robusto a errores de tilde)."""
    nfkd = unicodedata.normalize("NFD", word.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\wÀ-ÖØ-öø-ÿ]+", text)


def lexical_overlap(vlm_text: str, base_words: list[str]) -> float:
    """Fracción de palabras base (>= 4 letras) presentes en el texto VLM."""
    base = {_fold(w) for w in base_words if len(w) >= MIN_WORD_LEN}
    if not base:
        return 1.0
    vlm = {_fold(t) for t in _tokens(vlm_text)}
    return len(base & vlm) / len(base)


def expected_langs(lang_pack: str) -> set[str]:
    """Idiomas admisibles según el pack OCR ('por+eng+spa' -> pt/en/es)."""
    return {_PACK2LANG[p] for p in lang_pack.split("+") if p in _PACK2LANG}


def verify_vlm_output(
    vlm_text: str,
    base_words: list[str],
    lang_pack: str,
    *,
    overlap_min: float = OVERLAP_MIN,
) -> VlmVerdict:
    """Acepta o rechaza la salida del VLM. Nunca la modifica."""
    text = (vlm_text or "").strip()
    if not text:
        return VlmVerdict(False, "vacio")

    lowered = text.lower()
    for marker in _CHATTER:
        if marker in lowered:
            return VlmVerdict(False, f"chachara: '{marker}'")

    useful_base = [w for w in base_words if len(w) >= MIN_WORD_LEN]
    if len(useful_base) >= MIN_BASE_WORDS:
        overlap = lexical_overlap(text, base_words)
        if overlap < overlap_min:
            return VlmVerdict(False, f"solape lexico {overlap:.2f} < {overlap_min}")

    if len(_tokens(text)) >= LANG_MIN_TOKENS:
        detected = detect_language(text)
        allowed = expected_langs(lang_pack)
        if allowed and detected not in allowed and detected != "unknown":
            return VlmVerdict(False, f"idioma '{detected}' fuera del pack")

    if len(text) > EXPLOSION_CHARS and len(useful_base) < EXPLOSION_MAX_BASE:
        return VlmVerdict(False, "explosion de longitud sin base")

    return VlmVerdict(True)
