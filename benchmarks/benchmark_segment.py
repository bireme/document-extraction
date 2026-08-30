"""Benchmark reproducible de la segmentación anterior y la optimizada.

Ejemplo:
  PYTHONPATH=src python benchmarks/benchmark_segment.py --modo anterior páginas/*.jpg
  PYTHONPATH=src python benchmarks/benchmark_segment.py --modo optimizado páginas/*.jpg
"""

from __future__ import annotations

import argparse
import gc
import json
import resource
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

from PIL import Image

from pdfsum.segment import Region, _valleys, detect_regions

_UMBRAL_CONTENIDO = 200
_MIN_COL_ANCHO = 30
_MIN_REGION_ALTO = 20
_GAP_BLOQUE = 25
_GUTTER_MIN = 40


def _previous_mask(img: Any) -> tuple[list[list[bool]], int, int]:
    """Copia exacta de la máscara anterior para mantener la comparación."""
    gray = img.convert("L")
    width, height = gray.size
    pixels = gray.load()
    mask = [
        [pixels[x, y] < _UMBRAL_CONTENIDO for y in range(height)]
        for x in range(width)
    ]
    return mask, width, height


def _previous_columns(img: Any) -> list[Region]:
    mask, width, height = _previous_mask(img)
    projection = [
        sum(mask[x][y] for y in range(height)) for x in range(width)
    ]
    gaps = [
        gap
        for gap in _valleys(projection)
        if gap[1] - gap[0] >= _GUTTER_MIN
    ]
    cuts = [0] + [(left + right) // 2 for left, right in gaps] + [width]
    columns: list[Region] = []
    for left, right in pairwise(cuts):
        if (
            right - left >= _MIN_COL_ANCHO
            and any(projection[x] > 0 for x in range(left, right))
        ):
            columns.append(Region(left, 0, right, height))
    return columns or [Region(0, 0, width, height)]


def _previous_region_content(mask: list[list[bool]], region: Region) -> int:
    return sum(
        mask[x][y]
        for x in range(region.left, region.right)
        for y in range(region.top, region.bottom)
    )


def _previous_regions(img: Any) -> list[Region]:
    mask, width, height = _previous_mask(img)
    columns = _previous_columns(img)
    regions: list[Region] = []
    for column in columns:
        sub = [
            [mask[x][y] for y in range(column.top, column.bottom)]
            for x in range(column.left, column.right)
        ]
        projection_y = [
            sum(sub[x][y] for x in range(len(sub)))
            for y in range(column.bottom - column.top)
        ]
        gaps = [
            (column.top + top, column.top + bottom)
            for top, bottom in _valleys(projection_y, min_run=_GAP_BLOQUE)
        ]
        cuts = [column.top] + [
            (top + bottom) // 2 for top, bottom in gaps
        ] + [column.bottom]
        for top, bottom in pairwise(cuts):
            candidate = Region(column.left, top, column.right, bottom)
            if (
                bottom - top >= _MIN_REGION_ALTO
                and _previous_region_content(mask, candidate) > 0
            ):
                regions.append(candidate)
    return regions or [Region(0, 0, width, height)]


def _benchmark_previous(img: Any) -> tuple[list[Region], dict[str, float]]:
    started = time.perf_counter()
    mask, _, _ = _previous_mask(img)
    mask_seconds = time.perf_counter() - started
    del mask
    gc.collect()

    started = time.perf_counter()
    columns = _previous_columns(img)
    columns_seconds = time.perf_counter() - started
    del columns
    gc.collect()

    started = time.perf_counter()
    regions = _previous_regions(img)
    segmentation_seconds = time.perf_counter() - started
    return regions, {
        "mascara_segundos": mask_seconds,
        "columnas_segundos": columns_seconds,
        "segmentacion_segundos": segmentation_seconds,
    }


def _benchmark_optimized(img: Any) -> tuple[list[Region], dict[str, float]]:
    timings: dict[str, float] = {}
    regions = detect_regions(img, timings=timings)
    return regions, timings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mide segmentación con imágenes ya renderizadas."
    )
    parser.add_argument(
        "--modo",
        choices=("anterior", "optimizado"),
        required=True,
        help="Implementación que se va a medir.",
    )
    parser.add_argument("imagenes", nargs="+", type=Path)
    args = parser.parse_args()
    benchmark = (
        _benchmark_previous
        if args.modo == "anterior"
        else _benchmark_optimized
    )
    for path in args.imagenes:
        with Image.open(path) as img:
            img.load()
            regions, timings = benchmark(img)
            result = {
                "pagina": path.name,
                "modo": args.modo,
                "ancho": img.width,
                "alto": img.height,
                **timings,
                "cantidad_regiones": len(regions),
                "regiones": [vars(region) for region in regions],
                "rss_pico_proceso_mib": (
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                ),
            }
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
