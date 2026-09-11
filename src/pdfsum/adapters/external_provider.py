"""Composición configurable de fuente y destino, fuera del dominio."""

from __future__ import annotations

from importlib import import_module

from ..external import InputSource, ResultStore


def build_external_provider(
    provider: str, config: dict
) -> tuple[InputSource, ResultStore]:
    """Carga una fábrica instalada de confianza con firma fábrica(config).

    La fábrica recibe la configuración external completa y devuelve fuente/store.
    Permite integrar otro almacenamiento sin modificar procesadores ni executor.
    """
    if provider == "mongodb":
        from .external_mongodb import build_mongodb_provider

        return build_mongodb_provider(config)
    module, separator, name = provider.partition(":")
    if not separator or not module or not name:
        raise ValueError("Provider externo inválido: use módulo:fábrica")
    factory = getattr(import_module(module), name)
    return factory(config)
