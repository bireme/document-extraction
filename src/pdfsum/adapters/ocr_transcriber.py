"""Adaptador de transcripción basado en poppler + Tesseract (capa externa).

Implementa el puerto Transcriber usando las herramientas ya validadas en el
piloto: pdftotext para clasificar/extraer nativos, y Tesseract (con fallback
manual) para escaneados. El OCR híbrido completo con VLM vive en el script
`ocr_pipeline.sh` del piloto; este adaptador cubre el camino nativo + Tesseract
directo, suficiente para el grueso del corpus.

Este módulo SÍ puede ejecutar procesos externos; es un adaptador, no dominio.
"""
from __future__ import annotations

import shutil
import subprocess

from ..contract import SourceKind, TranscriptResult

_TEXT_PER_PAGE = 100


def _run(cmd: list[str], timeout: int = 120) -> str:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )
    return proc.stdout


def _pdfinfo_pages(path: str) -> int:
    out = _run(["pdfinfo", path])
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


class OcrTranscriber:
    """Transcriptor poppler+Tesseract. Requiere pdftotext/pdfinfo/tesseract."""

    def __init__(self, lang: str = "por", dpi: int = 300):
        self.lang = lang
        self.dpi = dpi
        for tool in ("pdftotext", "pdfinfo"):
            if not shutil.which(tool):
                raise RuntimeError(f"falta herramienta requerida: {tool}")

    def transcribe(self, path: str) -> TranscriptResult:
        pages = _pdfinfo_pages(path)
        native = _run(["pdftotext", path, "-"])
        chars = len(native.replace(" ", "").replace("\n", ""))
        per_page = chars / pages if pages else 0

        if per_page >= _TEXT_PER_PAGE:
            return TranscriptResult(
                text=native, pages=pages, source_kind=SourceKind.NATIVO
            )
        # escaneado: OCR con Tesseract página a página (si está disponible)
        if not shutil.which("tesseract"):
            return TranscriptResult(
                text=native, pages=pages, source_kind=SourceKind.ESCANEADO
            )
        text = self._ocr(path, pages)
        return TranscriptResult(
            text=text, pages=pages, source_kind=SourceKind.ESCANEADO
        )

    def _ocr(self, path: str, pages: int) -> str:
        import tempfile
        from pathlib import Path

        chunks: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            for p in range(1, max(pages, 1) + 1):
                prefix = str(Path(td) / f"pg{p}")
                _run(["pdftoppm", "-jpeg", "-r", str(self.dpi),
                      "-f", str(p), "-l", str(p), path, prefix])
                imgs = sorted(Path(td).glob(f"pg{p}*.jpg"))
                if not imgs:
                    continue
                out = _run(["tesseract", str(imgs[0]), "stdout",
                            "-l", self.lang, "--psm", "1"])
                chunks.append(f"=== pág {p} ===\n{out}")
                for im in imgs:
                    im.unlink()
        return "\n".join(chunks)
