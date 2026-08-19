"""Adaptadores (capa externa): implementan los puertos del dominio.

Aquí SÍ se permite tocar procesos externos (Ollama, HTTP, subprocess). El
dominio no importa este paquete; son los adaptadores los que dependen del
dominio (regla de dependencia hexagonal).
"""
