"""Transcriptor híbrido (adaptador de aplicación).

Replica el OCR del pilotaje con paridad: por página, usa Tesseract si su
confianza es alta; si no, escala al VLM (puerto PageOCR). PDFs nativos se
extraen directo con pdftotext (sin OCR).

Composición:
  nativo -> pdftotext
  escaneado -> por página: Tesseract (psm 1, tsv) -> route_page()
                alta confianza: texto Tesseract
                baja confianza: PageOCR (VLM) si hay adaptador; si no, Tesseract.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..classify import (
    DEFAULT_TEXT_PER_PAGE_THRESHOLD,
    aggregate_source,
    route_pages,
)
from ..contract import PageOCR, SourceKind, TranscriptResult
from ..ocr_routing import (
    MIN_CONF,
    MIN_WORDS,
    parse_tsv_confidence,
    parse_tsv_lines,
    parse_tsv_words,
    route_page,
)
from ..segment import (
    SKEW_MIN_APPLY,
    detect_regions,
    estimate_skew,
    sort_reading_order,
    valid_regions,
)
from ..vlm_verify import verify_vlm_output

_logger = logging.getLogger(__name__)

# FASE18 (benchmark RESULTADOS-F18.md): región con OCR pobre y tinta alta
# sin VLM disponible se marca como no textual en lugar de emitir basura.
NON_TEXT_MARKER = "[región no textual: posible figura/tabla]"
_NON_TEXT_MAX_WORDS = 5
_NON_TEXT_MAX_CONF = 40.0
_NON_TEXT_MIN_INK = 0.05


def _ink_fraction(img: Any) -> float:
    """Fracción de píxeles oscuros (tinta) de una imagen."""
    gray = img if img.mode == "L" else img.convert("L")
    hist = gray.histogram()
    if gray is not img:
        gray.close()
    total = sum(hist)
    return sum(hist[:200]) / total if total else 0.0


def _run(cmd: list[str], timeout: int = 120) -> str:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )
    return proc.stdout


def _pdfinfo_pages(path: str) -> int:
    for line in _run(["pdfinfo", path]).splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


class HybridOcrTranscriber:
    """Transcriptor nativo + Tesseract con fallback VLM por confianza."""

    def __init__(
        self,
        lang: str = "por+eng+spa",
        dpi: int = 300,
        vlm: PageOCR | None = None,
        min_conf: float = MIN_CONF,
        min_words: int = MIN_WORDS,
        event_sink: Callable[..., None] | None = None,
    ):
        self.lang = lang
        self.dpi = dpi
        self.vlm = vlm
        self.min_conf = min_conf
        self.min_words = min_words
        self._event_sink = event_sink
        for tool in ("pdftotext", "pdfinfo", "pdftoppm"):
            if not shutil.which(tool):
                raise RuntimeError(f"falta herramienta requerida: {tool}")
        self.vlm_used_pages = 0

    def set_event_sink(
        self, sink: Callable[..., None] | None
    ) -> Callable[..., None] | None:
        """Configura el destino de eventos y devuelve el destino anterior."""
        previous = self._event_sink
        self._event_sink = sink
        return previous

    def _emit_event(self, event: str, **fields: Any) -> None:
        """Emite progreso al log estándar y, si existe, al log durable."""
        _logger.info(
            "Progreso del OCR por página",
            extra={"evento": event, **fields},
        )
        if self._event_sink is not None:
            self._event_sink(event, **fields)

    def transcribe(self, path: str) -> TranscriptResult:
        pages = _pdfinfo_pages(path)
        native = _run(["pdftotext", path, "-"])
        # FASE17: decisión POR PÁGINA (pdftotext separa páginas con \f).
        native_pages = native.split("\f")[: pages or None]
        if pages and len(native_pages) < pages:
            native_pages += [""] * (pages - len(native_pages))
        page_chars = [len(p.replace(" ", "").replace("\n", "")) for p in native_pages]
        decisions = route_pages(page_chars, DEFAULT_TEXT_PER_PAGE_THRESHOLD)
        kind = aggregate_source(decisions) if pages else SourceKind.ESCANEADO

        if kind == SourceKind.NATIVO:
            return TranscriptResult(
                text=native,
                pages=pages,
                source_kind=SourceKind.NATIVO,
                pages_detail=[
                    {"page": p, "source": "nativo", "chars": page_chars[p - 1]}
                    for p in range(1, pages + 1)
                ],
            )
        if not shutil.which("tesseract"):
            return TranscriptResult(
                text=native, pages=pages, source_kind=SourceKind.ESCANEADO
            )
        if kind == SourceKind.ESCANEADO:
            text, pages_detail = self._ocr_hybrid(path, pages)
            return TranscriptResult(
                text=text,
                pages=pages,
                source_kind=SourceKind.ESCANEADO,
                pages_detail=pages_detail,
            )
        # MIXTO: solo las páginas pobres pasan por OCR; las nativas se
        # toman del pdftotext ya hecho. Marcador en TODAS las páginas.
        chunks: list[str] = []
        pages_detail: list[dict] = []
        with tempfile.TemporaryDirectory() as td:
            for p in range(1, pages + 1):
                if decisions[p - 1] == "nativo":
                    page_text = native_pages[p - 1].strip("\n")
                    chunks.append(f"=== pág {p} ===\n{page_text}")
                    pages_detail.append(
                        {
                            "page": p,
                            "source": "nativo",
                            "chars": len(page_text),
                        }
                    )
                else:
                    text, detail = self._ocr_single_page(path, p, pages, td)
                    chunks.append(f"=== pág {p} ===\n{text}")
                    pages_detail.append(detail)
        return TranscriptResult(
            text="\n".join(chunks),
            pages=pages,
            source_kind=SourceKind.MIXTO,
            pages_detail=pages_detail,
        )

    def _ocr_regions(self, img: Path, metrics: dict[str, Any] | None = None) -> str:
        """Segmenta la página y hace OCR por región, ensamblando en orden."""
        from PIL import Image

        segment_timings: dict[str, float] = {}
        fallback_before = self.vlm_used_pages
        with Image.open(img) as im:
            regs = sort_reading_order(
                valid_regions(detect_regions(im, timings=segment_timings), *im.size)
            )
            segmentation_finished = time.perf_counter()
            partes: list[str] = []
            confs: list[tuple[float, int]] = []  # (conf, words) por región
            non_text = 0
            vlm_accepted = False
            vlm_rejected = False
            vlm_motivo: str | None = None
            for region in regs:
                tmp = img.parent / f"_reg_{region.left}_{region.top}.png"
                try:
                    with im.crop(
                        (region.left, region.top, region.right, region.bottom)
                    ) as crop:
                        crop.save(tmp)
                        ink = _ink_fraction(crop)
                    texto, conf, words, info = self._ocr_page(tmp)
                    vlm_accepted = vlm_accepted or info["vlm"]
                    if info["vlm_rejected"]:
                        vlm_rejected = True
                        vlm_motivo = vlm_motivo or info["motivo"]
                    if (
                        self.vlm is None
                        and words < _NON_TEXT_MAX_WORDS
                        and conf < _NON_TEXT_MAX_CONF
                        and ink > _NON_TEXT_MIN_INK
                    ):
                        # FASE18 C7: aviso en vez de basura OCR.
                        partes.append(NON_TEXT_MARKER)
                        non_text += 1
                    else:
                        partes.append(texto)
                        if words:
                            confs.append((conf, words))
                finally:
                    tmp.unlink(missing_ok=True)
        total_words = sum(w for _, w in confs)
        conf_media = sum(c * w for c, w in confs) / total_words if total_words else 0.0
        del fallback_before  # FASE19: el uso VLM se rastrea por región
        if metrics is not None:
            metrics.update(segment_timings)
            metrics.update(
                {
                    "regiones": len(regs),
                    "ocr_segundos": time.perf_counter() - segmentation_finished,
                    "fallback_vlm": vlm_accepted,
                    "vlm_rechazado": vlm_rejected,
                    "vlm_motivo": vlm_motivo,
                    "conf_media": conf_media,
                    "palabras": total_words,
                    "non_text_regions": non_text,
                }
            )
        return "\n".join(p for p in partes if p.strip())

    def _ocr_page(self, img: Path) -> tuple[str, float, int, dict]:
        """Tesseract con routing por confianza -> VLM verificado si procede.

        Devuelve (texto, confianza_tesseract, palabras, info) donde info
        registra el uso/rechazo del VLM (FASE19: nunca vacío silencioso).
        """
        no_vlm = {"vlm": False, "vlm_rejected": False, "motivo": None}
        tsv = _run(
            ["tesseract", str(img), "stdout", "-l", self.lang, "--psm", "1", "tsv"]
        )
        conf, words = parse_tsv_confidence(tsv)
        if route_page(conf, words, self.min_conf, self.min_words) == "tesseract":
            text = _run(
                ["tesseract", str(img), "stdout", "-l", self.lang, "--psm", "1"]
            )
            return text, conf, words, no_vlm
        # baja confianza: fallback VLM verificado (1 reintento, FASE19)
        if self.vlm is not None:
            base_words = parse_tsv_words(tsv)
            verdict = None
            for _attempt in range(2):
                try:
                    candidate = self.vlm.ocr_image(str(img), self.lang)
                except Exception:  # noqa: BLE001 - error del VLM = rechazo
                    candidate = ""
                verdict = verify_vlm_output(candidate, base_words, self.lang)
                if verdict.accepted:
                    self.vlm_used_pages += 1
                    return (
                        candidate,
                        conf,
                        words,
                        {"vlm": True, "vlm_rejected": False, "motivo": None},
                    )
            # rechazado dos veces: degradar al texto Tesseract del routing
            return (
                parse_tsv_lines(tsv),
                conf,
                words,
                {"vlm": False, "vlm_rejected": True, "motivo": verdict.reason},
            )
        # sin VLM: degradar a Tesseract pese a baja confianza
        text = _run(["tesseract", str(img), "stdout", "-l", self.lang, "--psm", "1"])
        return text, conf, words, no_vlm

    def _ocr_single_page(
        self, path: str, p: int, pages_total: int, td: str
    ) -> tuple[str, dict]:
        """Rasteriza y OCRea UNA página; devuelve (texto, detalle F16)."""
        self._emit_event(
            "ocr_pagina_iniciada",
            doc_id=Path(path).stem,
            pagina=p,
            paginas_total=pages_total,
        )
        prefix = str(Path(td) / f"pg{p}")
        render_started = time.perf_counter()
        # FASE18 (benchmark RESULTADOS-F18.md): render -gray (PGM, sin
        # artefactos JPEG ni coste PNG) + autocontraste + deskew medido:
        # combo +5.9% palabras, +0.5 conf, -15% tiempo vs baseline JPEG.
        _run(
            [
                "pdftoppm",
                "-gray",
                "-r",
                str(self.dpi),
                "-f",
                str(p),
                "-l",
                str(p),
                path,
                prefix,
            ]
        )
        render_seconds = time.perf_counter() - render_started
        imgs = sorted(Path(td).glob(f"pg{p}*.pgm"))
        if not imgs:
            self._emit_event(
                "ocr_pagina_sin_imagen",
                doc_id=Path(path).stem,
                pagina=p,
                paginas_total=pages_total,
                render_segundos=round(render_seconds, 6),
            )
            # FASE16: página perdida visible para el gate 'paginas'.
            return "", {"page": p, "source": "sin_imagen", "chars": 0}
        page_img, skew_angle = self._preprocess_page(imgs[0])
        metrics: dict[str, Any] = {}
        text = self._ocr_regions(page_img, metrics)
        detail = {
            "page": p,
            "source": "vlm" if metrics["fallback_vlm"] else "tesseract",
            "conf": round(metrics["conf_media"], 2),
            "words": metrics["palabras"],
            "chars": len(text),
        }
        if skew_angle:
            detail["deskew_angle"] = skew_angle
        if metrics.get("non_text_regions"):
            detail["non_text_regions"] = metrics["non_text_regions"]
        if metrics.get("vlm_rechazado"):
            detail["vlm_rejected"] = True
            detail["vlm_motivo"] = metrics.get("vlm_motivo")
            self._emit_event(
                "vlm_rechazado",
                doc_id=Path(path).stem,
                pagina=p,
                motivo=metrics.get("vlm_motivo"),
            )
        self._emit_event(
            "ocr_pagina_completada",
            doc_id=Path(path).stem,
            pagina=p,
            paginas_total=pages_total,
            render_segundos=round(render_seconds, 6),
            mascara_segundos=round(metrics["mascara_segundos"], 6),
            columnas_segundos=round(metrics["columnas_segundos"], 6),
            regiones_segundos=round(metrics["regiones_segundos"], 6),
            segmentacion_segundos=round(metrics["segmentacion_segundos"], 6),
            regiones=metrics["regiones"],
            ocr_segundos=round(metrics["ocr_segundos"], 6),
            fallback_vlm=metrics["fallback_vlm"],
        )
        for im in imgs:
            im.unlink()
        return text, detail

    def _preprocess_page(self, img: Path) -> tuple[Path, float]:
        """FASE18: autocontraste + deskew (cadena 'combo' del benchmark).

        Devuelve (ruta imagen lista para OCR, ángulo aplicado o 0.0).
        """
        from PIL import Image, ImageOps

        angle_applied = 0.0
        with Image.open(img) as im:
            out = ImageOps.autocontrast(im.convert("L"))
            angle = estimate_skew(out)
            if abs(angle) >= SKEW_MIN_APPLY:
                rotated = out.rotate(
                    angle,
                    resample=Image.Resampling.BILINEAR,
                    expand=True,
                    fillcolor=255,
                )
                out.close()
                out = rotated
                angle_applied = round(angle, 2)
            dest = img.parent / f"{img.stem}_prep.pgm"
            out.save(dest, format="PPM")
            out.close()
        return dest, angle_applied

    def _ocr_hybrid(self, path: str, pages: int) -> tuple[str, list[dict]]:
        chunks: list[str] = []
        pages_detail: list[dict] = []
        with tempfile.TemporaryDirectory() as td:
            for p in range(1, max(pages, 1) + 1):
                text, detail = self._ocr_single_page(path, p, pages, td)
                pages_detail.append(detail)
                if detail["source"] == "sin_imagen":
                    continue
                chunks.append(f"=== pág {p} ===\n{text}")
        return "\n".join(chunks), pages_detail
