"""Segmentación de página en regiones (DOMINIO PURO).

Lección del primer análisis del piloto: pasar la página entera al VLM falla por
downscale. Hay que segmentar en columnas / bloques / recuadros y procesar cada
región a resolución legible.

Detección por proyección de píxeles de contenido (texto = píxeles oscuros sobre
fondo claro), usando solo Pillow (sin cv2). No importa adaptadores ni procesos
externos: trabaja sobre una imagen PIL y devuelve cajas.

Estrategia (determinista):
  1. Umbral de contenido (píxel oscuro) en escala de grises.
  2. Columnas: proyección vertical (conteo por columna x); cortes en valles.
  3. Dentro de cada columna, bloques verticales: proyección horizontal.
  4. Ensamble en orden de lectura (izq->der, arriba->abajo).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

_pairwise = pairwise

_UMBRAL_CONTENIDO = 200   # píxel < umbral en gris = contenido (texto)
_MIN_COL_ANCHO = 30       # ancho mínimo de columna (px)
_MIN_REGION_ALTO = 20     # alto mínimo de una región válida (px)
_GAP_BLOQUE = 25          # hueco vertical que separa bloques/párrafos (px)
_GUTTER_MIN = 40          # ancho mínimo de canal en blanco entre columnas (px)
_MARGEN = 6               # margen alrededor de cada región


@dataclass
class Region:
    """Una sub-área de la página: caja (left, top, right, bottom)."""

    left: int
    top: int
    right: int
    bottom: int

    def area(self) -> int:
        return max(0, self.right - self.left) * max(0, self.bottom - self.top)


def _content_mask(img: Any) -> tuple[list[list[bool]], int, int]:
    """Máscara booleana de contenido (True = píxel de texto)."""
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()
    mask = [[px[x, y] < _UMBRAL_CONTENIDO for y in range(h)] for x in range(w)]
    return mask, w, h


def _valleys(proj: list[int], min_run: int = 8) -> list[tuple[int, int]]:
    """Tramos en blanco (start,end) de la proyección 1D."""
    out: list[tuple[int, int]] = []
    start = -1
    for i, v in enumerate(proj):
        if v == 0:
            if start < 0:
                start = i
        else:
            if start >= 0 and i - start >= min_run:
                out.append((start, i))
            start = -1
    if start >= 0 and len(proj) - start >= min_run:
        out.append((start, len(proj)))
    return out


def detect_columns(img: Any) -> list[Region]:
    """Divide la página en columnas por proyección vertical (canal ancho)."""
    mask, w, h = _content_mask(img)
    proj = [sum(mask[x][y] for y in range(h)) for x in range(w)]
    # solo canales en blanco suficientemente anchos son separadores de columna
    gaps = [g for g in _valleys(proj) if (g[1] - g[0]) >= _GUTTER_MIN]
    cuts = [0] + [(a + b) // 2 for a, b in gaps] + [w]
    cols: list[Region] = []
    for a, b in _pairwise(cuts):
        # solo columnas con contenido y ancho mínimo
        if b - a >= _MIN_COL_ANCHO and any(proj[x] > 0 for x in range(a, b)):
            cols.append(Region(a, 0, b, h))
    if not cols:
        cols = [Region(0, 0, w, h)]
    return cols


def _region_content(mask: list[list[bool]], r: Region) -> int:
    """Píxeles de contenido dentro de una región."""
    return sum(mask[x][y]
               for x in range(r.left, r.right)
               for y in range(r.top, r.bottom))


def detect_regions(img: Any) -> list[Region]:
    """Divide en regiones: columnas -> bloques verticales dentro de cada una."""
    mask, w, h = _content_mask(img)
    cols = detect_columns(img)
    regions: list[Region] = []
    for col in cols:
        sub = [[mask[x][y] for y in range(col.top, col.bottom)]
               for x in range(col.left, col.right)]
        proj_y = [sum(sub[x][y] for x in range(len(sub)))
                  for y in range(col.bottom - col.top)]
        vgaps = [(col.top + a, col.top + b)
                 for a, b in _valleys(proj_y, min_run=_GAP_BLOQUE)]
        cuts = [col.top] + [(a + b) // 2 for a, b in vgaps] + [col.bottom]
        for a, b in _pairwise(cuts):
            cand = Region(col.left, a, col.right, b)
            if (b - a) >= _MIN_REGION_ALTO and _region_content(mask, cand) > 0:
                regions.append(cand)
    return regions or [Region(0, 0, w, h)]


def sort_reading_order(regions: list[Region]) -> list[Region]:
    """Orden de lectura: primero por columna (izq->der), dentro por arriba->abajo."""
    return sorted(regions, key=lambda r: (r.left, r.top))


def _valid(r: Region, w: int, h: int) -> bool:
    return (0 <= r.left < r.right <= w) and (0 <= r.top < r.bottom <= h)


def valid_regions(regions: list[Region], w: int, h: int) -> list[Region]:
    """Filtra regiones inválidas, de área/altura mínima, y duplicadas."""
    out: list[Region] = []
    seen = set()
    for r in regions:
        key = (r.left, r.top, r.right, r.bottom)
        if not _valid(r, w, h):
            continue
        if r.area() <= 0 or (r.bottom - r.top) < _MIN_REGION_ALTO:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
