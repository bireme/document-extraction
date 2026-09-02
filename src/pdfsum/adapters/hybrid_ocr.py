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

from ..classify import DEFAULT_TEXT_PER_PAGE_THRESHOLD
from ..contract import PageOCR, SourceKind, TranscriptResult
from ..ocr_routing import MIN_CONF, MIN_WORDS, parse_tsv_confidence, route_page
from ..segment import detect_regions, sort_reading_order, valid_regions

_logger = logging.getLogger(__name__)


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
        chars = len(native.replace(" ", "").replace("\n", ""))
        if pages and chars / pages >= DEFAULT_TEXT_PER_PAGE_THRESHOLD:
            return TranscriptResult(
                text=native,
                pages=pages,
                source_kind=SourceKind.NATIVO,
                pages_detail=[
                    {"page": p, "source": "nativo"} for p in range(1, pages + 1)
                ],
            )
        if not shutil.which("tesseract"):
            return TranscriptResult(
                text=native, pages=pages, source_kind=SourceKind.ESCANEADO
            )
        text, pages_detail = self._ocr_hybrid(path, pages)
        return TranscriptResult(
            text=text,
            pages=pages,
            source_kind=SourceKind.ESCANEADO,
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
            for region in regs:
                tmp = img.parent / f"_reg_{region.left}_{region.top}.png"
                try:
                    with im.crop(
                        (region.left, region.top, region.right, region.bottom)
                    ) as crop:
                        crop.save(tmp)
                    texto, conf, words = self._ocr_page(tmp)
                    partes.append(texto)
                    if words:
                        confs.append((conf, words))
                finally:
                    tmp.unlink(missing_ok=True)
        total_words = sum(w for _, w in confs)
        conf_media = sum(c * w for c, w in confs) / total_words if total_words else 0.0
        if metrics is not None:
            metrics.update(segment_timings)
            metrics.update(
                {
                    "regiones": len(regs),
                    "ocr_segundos": time.perf_counter() - segmentation_finished,
                    "fallback_vlm": self.vlm_used_pages > fallback_before,
                    "conf_media": conf_media,
                    "palabras": total_words,
                }
            )
        return "\n".join(p for p in partes if p.strip())

    def _ocr_page(self, img: Path) -> tuple[str, float, int]:
        """Tesseract con routing por confianza -> VLM si procede.

        Devuelve (texto, confianza_tesseract, palabras): la confianza medida
        se conserva SIEMPRE (FASE16), aunque la región termine en VLM.
        """
        tsv = _run(
            ["tesseract", str(img), "stdout", "-l", self.lang, "--psm", "1", "tsv"]
        )
        conf, words = parse_tsv_confidence(tsv)
        if route_page(conf, words, self.min_conf, self.min_words) == "tesseract":
            text = _run(
                ["tesseract", str(img), "stdout", "-l", self.lang, "--psm", "1"]
            )
            return text, conf, words
        # baja confianza: fallback VLM si hay adaptador
        if self.vlm is not None:
            self.vlm_used_pages += 1
            return self.vlm.ocr_image(str(img), self.lang), conf, words
        # sin VLM: degradar a Tesseract pese a baja confianza
        text = _run(["tesseract", str(img), "stdout", "-l", self.lang, "--psm", "1"])
        return text, conf, words

    def _ocr_hybrid(self, path: str, pages: int) -> tuple[str, list[dict]]:
        chunks: list[str] = []
        pages_detail: list[dict] = []
        with tempfile.TemporaryDirectory() as td:
            for p in range(1, max(pages, 1) + 1):
                self._emit_event(
                    "ocr_pagina_iniciada",
                    doc_id=Path(path).stem,
                    pagina=p,
                    paginas_total=pages,
                )
                prefix = str(Path(td) / f"pg{p}")
                render_started = time.perf_counter()
                _run(
                    [
                        "pdftoppm",
                        "-jpeg",
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
                imgs = sorted(Path(td).glob(f"pg{p}*.jpg"))
                if not imgs:
                    self._emit_event(
                        "ocr_pagina_sin_imagen",
                        doc_id=Path(path).stem,
                        pagina=p,
                        paginas_total=pages,
                        render_segundos=round(render_seconds, 6),
                    )
                    # FASE16: página perdida visible para el gate 'paginas'.
                    pages_detail.append({"page": p, "source": "sin_imagen", "chars": 0})
                    continue
                metrics: dict[str, Any] = {}
                text = self._ocr_regions(imgs[0], metrics)
                chunks.append(f"=== pág {p} ===\n{text}")
                pages_detail.append(
                    {
                        "page": p,
                        "source": "vlm" if metrics["fallback_vlm"] else "tesseract",
                        "conf": round(metrics["conf_media"], 2),
                        "words": metrics["palabras"],
                        "chars": len(text),
                    }
                )
                self._emit_event(
                    "ocr_pagina_completada",
                    doc_id=Path(path).stem,
                    pagina=p,
                    paginas_total=pages,
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
        return "\n".join(chunks), pages_detail
