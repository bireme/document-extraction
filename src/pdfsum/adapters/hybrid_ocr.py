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

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..contract import PageOCR, SourceKind, TranscriptResult
from ..ocr_routing import MIN_CONF, MIN_WORDS, parse_tsv_confidence, route_page
from ..segment import detect_regions, sort_reading_order, valid_regions

_TEXT_PER_PAGE = 100


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
        lang: str = "por",
        dpi: int = 300,
        vlm: PageOCR | None = None,
        min_conf: float = MIN_CONF,
        min_words: int = MIN_WORDS,
    ):
        self.lang = lang
        self.dpi = dpi
        self.vlm = vlm
        self.min_conf = min_conf
        self.min_words = min_words
        for tool in ("pdftotext", "pdfinfo", "pdftoppm"):
            if not shutil.which(tool):
                raise RuntimeError(f"falta herramienta requerida: {tool}")
        self.vlm_used_pages = 0

    def transcribe(self, path: str) -> TranscriptResult:
        pages = _pdfinfo_pages(path)
        native = _run(["pdftotext", path, "-"])
        chars = len(native.replace(" ", "").replace("\n", ""))
        if pages and chars / pages >= _TEXT_PER_PAGE:
            return TranscriptResult(
                text=native, pages=pages, source_kind=SourceKind.NATIVO)
        if not shutil.which("tesseract"):
            return TranscriptResult(
                text=native, pages=pages, source_kind=SourceKind.ESCANEADO)
        return TranscriptResult(
            text=self._ocr_hybrid(path, pages), pages=pages,
            source_kind=SourceKind.ESCANEADO)

    def _ocr_regions(self, img: Path) -> str:
        """Segmenta la página y hace OCR por región, ensamblando en orden."""
        from PIL import Image
        im = Image.open(img)
        regs = sort_reading_order(valid_regions(detect_regions(im), *im.size))
        partes: list[str] = []
        for r in regs:
            crop = im.crop((r.left, r.top, r.right, r.bottom))
            tmp = img.parent / f"_reg_{r.left}_{r.top}.png"
            crop.save(tmp)
            partes.append(self._ocr_page(tmp))
            tmp.unlink()
        return "\n".join(p for p in partes if p.strip())

    def _ocr_page(self, img: Path) -> str:
        """Tesseract con routing por confianza -> VLM si procede."""
        tsv = _run(["tesseract", str(img), "stdout", "-l", self.lang,
                    "--psm", "1", "tsv"])
        conf, words = parse_tsv_confidence(tsv)
        if route_page(conf, words, self.min_conf, self.min_words) == "tesseract":
            return _run(["tesseract", str(img), "stdout", "-l", self.lang,
                         "--psm", "1"])
        # baja confianza: fallback VLM si hay adaptador
        if self.vlm is not None:
            self.vlm_used_pages += 1
            return self.vlm.ocr_image(str(img), self.lang)
        # sin VLM: degradar a Tesseract pese a baja confianza
        return _run(["tesseract", str(img), "stdout", "-l", self.lang,
                     "--psm", "1"])

    def _ocr_hybrid(self, path: str, pages: int) -> str:
        chunks: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            for p in range(1, max(pages, 1) + 1):
                prefix = str(Path(td) / f"pg{p}")
                _run(["pdftoppm", "-jpeg", "-r", str(self.dpi),
                      "-f", str(p), "-l", str(p), path, prefix])
                imgs = sorted(Path(td).glob(f"pg{p}*.jpg"))
                if not imgs:
                    continue
                chunks.append(f"=== pág {p} ===\n{self._ocr_regions(imgs[0])}")
                for im in imgs:
                    im.unlink()
        return "\n".join(chunks)
