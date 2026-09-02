"""Benchmark FASE18: efecto de cada técnica de preprocesado sobre el OCR.

Mide, por página escaneada y por técnica, la confianza media y palabras de
Tesseract (TSV) y el tiempo total (render + preprocesado + OCR). El VLM se
excluye a propósito: contaminaría la medición (lo que se evalúa es cuánto
mejora la señal que ve Tesseract).

Técnicas:
  baseline      pdftoppm -jpeg 300dpi (comportamiento actual)
  gray          pdftoppm -gray (PGM sin compresión ni artefactos, render
                ~100x más rápido que -png según medición previa)
  autocontrast  gray + ImageOps.autocontrast
  deskew        gray + rotación por estimate_skew (si |ángulo| >= 0.5)
  combo         gray + autocontrast + deskew
  lang_por      jpeg baseline con pack único 'por' (vs por+eng+spa)

Uso:
  PYTHONPATH=src python benchmarks/benchmark_ocr_quality.py \
      --pdfs <dir-o-ficheros> --out benchmarks/RESULTADOS-F18.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageOps

from pdfsum.ocr_routing import parse_tsv_confidence
from pdfsum.segment import SKEW_MIN_APPLY, estimate_skew

LANG_COMBI = "por+eng+spa"
DPI = 300


def _run(cmd: list[str], timeout: int = 300) -> str:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    ).stdout


def _pages(pdf: Path) -> int:
    for line in _run(["pdfinfo", str(pdf)]).splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def _render(pdf: Path, page: int, fmt: str, td: Path) -> Path | None:
    prefix = td / f"{pdf.stem}_p{page}_{fmt}"
    flag = {"jpeg": "-jpeg", "gray": "-gray"}[fmt]
    _run(
        [
            "pdftoppm",
            flag,
            "-r",
            str(DPI),
            "-f",
            str(page),
            "-l",
            str(page),
            str(pdf),
            str(prefix),
        ]
    )
    hits = sorted(td.glob(f"{prefix.name}*"))
    return hits[0] if hits else None


def _tesseract_tsv(img: Path, lang: str) -> tuple[float, int]:
    tsv = _run(["tesseract", str(img), "stdout", "-l", lang, "--psm", "1", "tsv"])
    return parse_tsv_confidence(tsv)


def _apply(img_path: Path, technique: str, td: Path) -> tuple[Path, float]:
    """Aplica el preprocesado; devuelve (imagen_lista, ángulo_detectado)."""
    angle = 0.0
    if technique in ("baseline", "gray", "lang_por"):
        return img_path, angle
    with Image.open(img_path) as im:
        out = im.convert("L")
        if technique in ("autocontrast", "combo"):
            out = ImageOps.autocontrast(out)
        if technique in ("deskew", "combo"):
            angle = estimate_skew(out)
            if abs(angle) >= SKEW_MIN_APPLY:
                out = out.rotate(
                    angle,
                    resample=Image.Resampling.BILINEAR,
                    expand=True,
                    fillcolor=255,
                )
        dest = td / f"{img_path.stem}_{technique}.pgm"
        out.save(dest, format="PPM")
        out.close()
    return dest, angle


def bench_page(pdf: Path, page: int, td: Path) -> list[dict]:
    rows = []
    for technique in (
        "baseline",
        "gray",
        "autocontrast",
        "deskew",
        "combo",
        "lang_por",
    ):
        fmt = "jpeg" if technique in ("baseline", "lang_por") else "gray"
        lang = "por" if technique == "lang_por" else LANG_COMBI
        started = time.perf_counter()
        raw = _render(pdf, page, fmt, td)
        if raw is None:
            continue
        img, angle = _apply(raw, technique, td)
        conf, words = _tesseract_tsv(img, lang)
        rows.append(
            {
                "pdf": pdf.stem,
                "page": page,
                "technique": technique,
                "conf": round(conf, 2),
                "words": words,
                "seconds": round(time.perf_counter() - started, 2),
                "angle": round(angle, 2),
            }
        )
    return rows


def to_markdown(rows: list[dict]) -> str:
    techniques = ["baseline", "gray", "autocontrast", "deskew", "combo", "lang_por"]
    agg: dict[str, dict] = {}
    for t in techniques:
        sel = [r for r in rows if r["technique"] == t]
        if not sel:
            continue
        total_words = sum(r["words"] for r in sel) or 1
        agg[t] = {
            "pages": len(sel),
            "conf": sum(r["conf"] * r["words"] for r in sel) / total_words,
            "words": sum(r["words"] for r in sel),
            "seconds": sum(r["seconds"] for r in sel),
        }
    base = agg.get("baseline")
    lines = [
        "| técnica | págs | conf media | Δconf | palabras | Δpal % | segundos | Δt % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for t in techniques:
        if t not in agg:
            continue
        a = agg[t]
        dconf = a["conf"] - base["conf"]
        dwords = 100 * (a["words"] - base["words"]) / max(base["words"], 1)
        dt = 100 * (a["seconds"] - base["seconds"]) / max(base["seconds"], 0.01)
        lines.append(
            f"| {t} | {a['pages']} | {a['conf']:.2f} | {dconf:+.2f} "
            f"| {a['words']} | {dwords:+.1f}% | {a['seconds']:.1f} | {dt:+.1f}% |"
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", nargs="+", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-pages", type=int, default=4)
    args = ap.parse_args()

    pdfs: list[Path] = []
    for p in args.pdfs:
        path = Path(p)
        pdfs += sorted(path.glob("*.pdf")) if path.is_dir() else [path]

    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        for pdf in pdfs:
            for page in range(1, min(_pages(pdf), args.max_pages) + 1):
                rows += bench_page(pdf, page, Path(td))
                print(f"{pdf.stem} pág {page} ok", flush=True)

    table = to_markdown(rows)
    print(table)
    if args.out:
        out = Path(args.out)
        body = (
            "# Resultados benchmark FASE18 — preprocesado OCR\n\n"
            f"PDFs: {', '.join(p.stem for p in pdfs)} (máx "
            f"{args.max_pages} págs c/u, {DPI} dpi, lang {LANG_COMBI})\n\n"
            + table
            + "\n\n## Detalle por página\n\n```json\n"
            + json.dumps(rows, ensure_ascii=False, indent=1)
            + "\n```\n"
        )
        out.write_text(body, encoding="utf-8")
        print(f"\nescrito: {out}")


if __name__ == "__main__":
    main()
