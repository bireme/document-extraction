"""Consolidación inteligente de resúmenes parciales (DOMINIO PURO).

Para resumen jerárquico: cuando consolidamos múltiples resúmenes de capítulos
(o bloques) en un resumen final, algunos campos (publico, terminos) tienden a
repetirse/apilarse sin añadir valor. Esta lógica los deduplica y fusiona en
listas únicas y coherentes.
"""

from __future__ import annotations


def deduplicate_field(values: list[str]) -> str:
    """Deduplica una lista de valores y devuelve una sola cadena formateada.

    Valores vacíos se descartan. Si hay solo uno, se devuelve directo.
    Si hay varios, se convierten a conjunto (único orden) y se juntan con
    saltos de línea.

    Args:
        values: lista de strings (posiblemente con repeticiones).

    Returns:
        string único y deduplica do (o vacío si no hay valores).
    """
    if not values:
        return ""

    # Dividir cada valor por saltos de línea, aplana, y deduplica
    items = set()
    for v in values:
        if not v or not v.strip():
            continue
        for line in v.split("\n"):
            line = line.strip()
            # Elimina bullets/guiones comunes
            if line.startswith("- "):
                line = line[2:].strip()
            if line.startswith("• "):
                line = line[2:].strip()
            if line:
                items.add(line)

    if not items:
        return ""

    return "\n".join(f"- {item}" for item in sorted(items))


def consolidate_sections(
    partials: list[dict[str, str]],
    dedup_fields: list[str] | None = None,
) -> dict[str, str]:
    """Consolida múltiples resúmenes parciales en uno único.

    Para campos en dedup_fields, aplica deduplicate_field().
    Para otros, concatena con saltos de párrafo.

    Args:
        partials: lista de dict {sección -> contenido} (e.g., de varios capítulos).
        dedup_fields: campos a deduplicar (default: ["publico", "terminos"]).

    Returns:
        dict consolida do {sección -> contenido}.
    """
    if not partials:
        return {}

    if dedup_fields is None:
        dedup_fields = ["publico", "terminos"]

    result: dict[str, str] = {}
    all_keys = {k for p in partials for k in p}

    for key in all_keys:
        values = [p.get(key, "") for p in partials if p.get(key, "").strip()]

        if key in dedup_fields:
            result[key] = deduplicate_field(values)
        else:
            # Campos narrativos: concatena con doble salto de línea
            result[key] = "\n\n".join(v for v in values if v.strip())

    return result
