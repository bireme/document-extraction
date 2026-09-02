"""Segmentación de página en regiones (DOMINIO PURO).

Lección del primer análisis del piloto: pasar la página entera al VLM falla por
downscale. Hay que segmentar en columnas / bloques / recuadros y procesar cada
región a resolución legible.

Detección por proyección de píxeles de contenido (texto = píxeles oscuros sobre
fondo claro), usando solo Pillow (sin cv2 ni NumPy). El análisis se hace sobre
una máscara reducida, pero las cajas devueltas siempre usan las coordenadas de
la imagen original.

Estrategia (determinista):
  1. Umbral de contenido (píxel oscuro) en escala de grises.
  2. Reducción de la máscara para abaratar las proyecciones.
  3. Columnas: proyección vertical (presencia por columna x); cortes en valles.
  4. Dentro de cada columna, bloques verticales: proyección horizontal.
  5. Proyección de las cajas a la resolución original con margen de seguridad.
"""

from __future__ import annotations

import math
import time
from collections.abc import MutableMapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

_pairwise = pairwise

_UMBRAL_CONTENIDO = 200  # píxel < umbral en gris = contenido (texto)
_MIN_COL_ANCHO = 30  # ancho mínimo de columna (px a resolución original)
_MIN_REGION_ALTO = 20  # alto mínimo de región (px a resolución original)
_GAP_BLOQUE = 25  # hueco vertical que separa bloques (px originales)
_GUTTER_MIN = 40  # ancho mínimo de canal entre columnas (px originales)
_MARGEN = 6  # margen de seguridad en las cajas proyectadas (px originales)
_ESCALA_DETECCION = 0.25


@dataclass
class Region:
    """Una sub-área de la página: caja (left, top, right, bottom)."""

    left: int
    top: int
    right: int
    bottom: int

    def area(self) -> int:
        return max(0, self.right - self.left) * max(0, self.bottom - self.top)


@dataclass
class _ContentMask:
    """Máscara reducida y datos necesarios para proyectar sus coordenadas."""

    image: Any
    original_width: int
    original_height: int

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    @property
    def scale_x(self) -> float:
        return self.width / self.original_width

    @property
    def scale_y(self) -> float:
        return self.height / self.original_height


def _content_mask(img: Any, scale: float = _ESCALA_DETECCION) -> _ContentMask:
    """Crea en Pillow una máscara reducida (255 = contenido, 0 = fondo)."""
    from PIL import Image

    original_width, original_height = img.size
    width = max(1, round(original_width * scale))
    height = max(1, round(original_height * scale))
    gray = img if img.mode == "L" else img.convert("L")
    table = [255 if value < _UMBRAL_CONTENIDO else 0 for value in range(256)]
    binary = gray.point(table, mode="L")
    if gray is not img:
        gray.close()

    if binary.size == (width, height):
        reduced = binary
    else:
        reduced = binary.resize((width, height), Image.Resampling.BOX)
        binary.close()
        # BOX puede producir niveles intermedios; cualquier píxel oscuro del
        # bloque original debe seguir contando como contenido.
        normalized = reduced.point([0] + [255] * 255, mode="L")
        reduced.close()
        reduced = normalized
    return _ContentMask(reduced, original_width, original_height)


def _scaled(value: int, scale: float) -> int:
    """Escala un límite geométrico sin permitir que desaparezca."""
    return max(1, math.ceil(value * scale))


def _valleys(proj: list[int], min_run: int = 8) -> list[tuple[int, int]]:
    """Tramos en blanco (start,end) de la proyección 1D."""
    out: list[tuple[int, int]] = []
    start = -1
    for i, value in enumerate(proj):
        if value == 0:
            if start < 0:
                start = i
        else:
            if start >= 0 and i - start >= min_run:
                out.append((start, i))
            start = -1
    if start >= 0 and len(proj) - start >= min_run:
        out.append((start, len(proj)))
    return out


def _detect_columns_reduced(mask: _ContentMask) -> list[Region]:
    """Detecta columnas dentro del sistema de coordenadas de la máscara."""
    projection_x, _ = mask.image.getprojection()
    projection_x = list(projection_x)
    gutter_min = _scaled(_GUTTER_MIN, mask.scale_x)
    gaps = [gap for gap in _valleys(projection_x) if (gap[1] - gap[0]) >= gutter_min]
    cuts = [0] + [(left + right) // 2 for left, right in gaps] + [mask.width]
    min_width = _scaled(_MIN_COL_ANCHO, mask.scale_x)
    columns: list[Region] = []
    for left, right in _pairwise(cuts):
        if right - left >= min_width and any(projection_x[left:right]):
            columns.append(Region(left, 0, right, mask.height))
    if not columns:
        columns = [Region(0, 0, mask.width, mask.height)]
    return columns


def _project_region(region: Region, mask: _ContentMask, margin: int = 0) -> Region:
    """Proyecta una caja reducida sin recortar sus bordes por redondeo."""
    left = region.left * mask.original_width // mask.width
    top = region.top * mask.original_height // mask.height
    right = math.ceil(region.right * mask.original_width / mask.width)
    bottom = math.ceil(region.bottom * mask.original_height / mask.height)
    return Region(
        max(0, left - margin),
        max(0, top - margin),
        min(mask.original_width, right + margin),
        min(mask.original_height, bottom + margin),
    )


def detect_columns(
    img: Any,
    _mask: _ContentMask | None = None,
    *,
    _reduced: bool = False,
) -> list[Region]:
    """Divide la página en columnas por proyección vertical (canal ancho).

    ``_mask`` permite que :func:`detect_regions` reutilice la máscara ya creada.
    Los parámetros privados conservan intacto el uso público habitual.
    """
    mask = _mask or _content_mask(img)
    columns = _detect_columns_reduced(mask)
    if _reduced:
        return columns
    return [_project_region(column, mask) for column in columns]


def _region_content(prefix: list[int], top: int, bottom: int) -> int:
    """Indica en O(1) cuántas filas con contenido abarca una región."""
    return prefix[bottom] - prefix[top]


def detect_regions(
    img: Any, *, timings: MutableMapping[str, float] | None = None
) -> list[Region]:
    """Divide en regiones usando una sola máscara reducida y reutilizable.

    Si se pasa ``timings``, se llena con segundos de máscara, columnas, regiones
    y segmentación total para facilitar mediciones reproducibles.
    """
    total_started = time.perf_counter()
    started = time.perf_counter()
    mask = _content_mask(img)
    mask_seconds = time.perf_counter() - started

    started = time.perf_counter()
    columns = detect_columns(img, mask, _reduced=True)
    columns_seconds = time.perf_counter() - started

    started = time.perf_counter()
    regions: list[Region] = []
    min_gap = _scaled(_GAP_BLOQUE, mask.scale_y)
    min_height = _scaled(_MIN_REGION_ALTO, mask.scale_y)
    for column in columns:
        column_mask = mask.image.crop(
            (column.left, column.top, column.right, column.bottom)
        )
        _, projection_y = column_mask.getprojection()
        column_mask.close()
        projection_y = list(projection_y)
        gaps = [
            (column.top + top, column.top + bottom)
            for top, bottom in _valleys(projection_y, min_run=min_gap)
        ]
        cuts = (
            [column.top]
            + [(top + bottom) // 2 for top, bottom in gaps]
            + [column.bottom]
        )
        prefix = [0]
        for value in projection_y:
            prefix.append(prefix[-1] + bool(value))
        for top, bottom in _pairwise(cuts):
            local_top = top - column.top
            local_bottom = bottom - column.top
            if (
                bottom - top >= min_height
                and _region_content(prefix, local_top, local_bottom) > 0
            ):
                regions.append(Region(column.left, top, column.right, bottom))

    if not regions:
        regions = [Region(0, 0, mask.width, mask.height)]
    projected = [_project_region(region, mask, _MARGEN) for region in regions]
    regions_seconds = time.perf_counter() - started
    total_seconds = time.perf_counter() - total_started
    if timings is not None:
        timings.update(
            {
                "mascara_segundos": mask_seconds,
                "columnas_segundos": columns_seconds,
                "regiones_segundos": regions_seconds,
                "segmentacion_segundos": total_seconds,
            }
        )
    return projected


# FASE18: búsqueda de ángulo de deskew (barrido grueso + refinamiento).
_SKEW_MAX = 3.0
_SKEW_COARSE = 0.5
_SKEW_FINE = 0.25
SKEW_MIN_APPLY = 0.5  # por debajo, no rotar (página ya recta)


def _projection_sharpness(mask_img: Any) -> float:
    """Varianza de la DENSIDAD de tinta por fila: máxima con líneas rectas.

    Nota: getprojection() de Pillow devuelve solo presencia 0/1 (inútil
    para nitidez); aquí se usa la media por fila vía resize BOX a 1 px
    de ancho, que sí distingue filas densas de huecos.
    """
    from PIL import Image

    height = mask_img.height
    if not height:
        return 0.0
    column = mask_img.resize((1, height), Image.Resampling.BOX)
    values = list(column.getdata())
    column.close()
    mean = sum(values) / height
    return sum((v - mean) ** 2 for v in values) / height


def estimate_skew(img: Any, max_angle: float = _SKEW_MAX) -> float:
    """Estima el ángulo de inclinación del texto (grados, DOMINIO PURO).

    Maximiza la nitidez de la proyección horizontal de la máscara reducida
    rotada en candidatos ±max_angle (grueso 0.5°, fino 0.25°). Positivo =
    la página debe rotarse ese ángulo (Image.rotate) para enderezarse.
    """
    from PIL import Image

    mask = _content_mask(img)
    base = mask.image

    def score(angle: float) -> float:
        if angle == 0.0:
            return _projection_sharpness(base)
        rotated = base.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=0)
        value = _projection_sharpness(rotated)
        rotated.close()
        return value

    candidates = [0.0]
    steps = int(max_angle / _SKEW_COARSE)
    candidates += [i * _SKEW_COARSE for i in range(-steps, steps + 1) if i]
    best = max(candidates, key=score)
    refined = [best - _SKEW_FINE, best, best + _SKEW_FINE]
    best = max(refined, key=score)
    base.close()
    return best


# FASE18: tolerancia de agrupación de columnas (medio gutter).
_COLUMN_TOLERANCE = _GUTTER_MIN // 2


def sort_reading_order(regions: list[Region]) -> list[Region]:
    """Orden de lectura: por columna (izq->der) y arriba->abajo dentro.

    FASE18: agrupa por columna con TOLERANCIA — bordes izquierdos que
    difieren menos de medio gutter pertenecen a la misma columna (el
    orden estricto por (left, top) desordenaba columnas desiguales).
    """
    if not regions:
        return []
    by_left = sorted(regions, key=lambda region: region.left)
    clusters: list[list[Region]] = [[by_left[0]]]
    for region in by_left[1:]:
        if region.left - clusters[-1][0].left <= _COLUMN_TOLERANCE:
            clusters[-1].append(region)
        else:
            clusters.append([region])
    out: list[Region] = []
    for cluster in clusters:
        out.extend(sorted(cluster, key=lambda region: (region.top, region.left)))
    return out


def _valid(region: Region, width: int, height: int) -> bool:
    return (
        0 <= region.left < region.right <= width
        and 0 <= region.top < region.bottom <= height
    )


def valid_regions(regions: list[Region], w: int, h: int) -> list[Region]:
    """Filtra regiones inválidas, de área/altura mínima, y duplicadas."""
    out: list[Region] = []
    seen = set()
    for region in regions:
        key = (region.left, region.top, region.right, region.bottom)
        if not _valid(region, w, h):
            continue
        if region.area() <= 0 or (region.bottom - region.top) < _MIN_REGION_ALTO:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(region)
    return out
