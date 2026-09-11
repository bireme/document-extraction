"""Punto de composición MongoDB, pendiente del contrato del schema real.

No selecciona documentos ni escribe colecciones hasta definir el mapeo,
reservas y persistencia. No importa pymongo desde el dominio ni al cargar CLI.
"""

from __future__ import annotations

import os
from importlib.util import find_spec


def build_mongodb_provider(config: dict):
    """Informa los requisitos sin conectar ni asumir campos de la base."""
    if find_spec("pymongo") is None:
        raise ValueError(
            "El provider MongoDB requiere la dependencia opcional pymongo; "
            "instálela para preparar la integración. El schema sigue pendiente"
        )
    if not os.environ.get("PDFSUM_MONGODB_URI"):
        raise ValueError("Falta la variable de entorno PDFSUM_MONGODB_URI")
    raise ValueError(
        "MongoDB pendiente de schema: faltan base/colecciones, mapeos de ID, "
        "URL y tipo, selección/reserva de pendientes, escritura y reintentos"
    )
