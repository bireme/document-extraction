"""Plantillas de resumen estructurado por tipo (DOMINIO PURO).

Catálogo del informe §3.1:
  A) Artículo científico  -> structured abstract normalizado (IMRAD).
  B) Manual / informe extenso.
  C) Material de divulgación (folleto, cartaz, edital).

Las secciones se nombran en el idioma del documento. Aquí definimos los nombres
canónicos por idioma; el adaptador resumidor los usa para construir el prompt y
para validar la salida.
"""
from __future__ import annotations

# Claves canónicas de sección por plantilla (independientes del idioma).
_KEYS = {
    "A": ["titulo", "autores", "tipo_estudio", "objetivo", "metodos",
          "resultados", "conclusiones", "palabras_clave"],
    "B": ["titulo", "tipo_documento", "entidad", "objeto_alcance",
          "estructura", "sintesis", "publico", "terminos"],
    "C": ["titulo", "tipo_documento", "entidad", "publico",
          "resumen_ejecutivo", "puntos_clave", "terminos"],
}

# Etiquetas legibles por idioma y clave (para render y para el prompt).
_LABELS: dict[str, dict[str, str]] = {
    "pt": {
        "titulo": "Título", "autores": "Autores / Filiação",
        "tipo_estudio": "Tipo de estudo", "objetivo": "Objetivo",
        "metodos": "Métodos", "resultados": "Resultados",
        "conclusiones": "Conclusões", "palabras_clave": "Palavras-chave",
        "tipo_documento": "Tipo de documento", "entidad": "Entidade(s) emissora(s)",
        "objeto_alcance": "Objeto e alcance", "estructura": "Estrutura",
        "sintesis": "Síntese por seção", "publico": "Público-alvo",
        "resumen_ejecutivo": "Resumo executivo",
        "puntos_clave": "Pontos-chave", "terminos": "Termos técnicos / entidades",
    },
    "es": {
        "titulo": "Título", "autores": "Autores / Filiación",
        "tipo_estudio": "Tipo de estudio", "objetivo": "Objetivo",
        "metodos": "Métodos", "resultados": "Resultados",
        "conclusiones": "Conclusiones", "palabras_clave": "Palabras clave",
        "tipo_documento": "Tipo de documento", "entidad": "Entidad(es) emisora(s)",
        "objeto_alcance": "Objeto y alcance", "estructura": "Estructura",
        "sintesis": "Síntesis por sección", "publico": "Público objetivo",
        "resumen_ejecutivo": "Resumen ejecutivo",
        "puntos_clave": "Puntos clave", "terminos": "Términos técnicos / entidades",
    },
    "en": {
        "titulo": "Title", "autores": "Authors / Affiliation",
        "tipo_estudio": "Study type", "objetivo": "Objective",
        "metodos": "Methods", "resultados": "Results",
        "conclusiones": "Conclusions", "palabras_clave": "Keywords",
        "tipo_documento": "Document type", "entidad": "Issuing entity(ies)",
        "objeto_alcance": "Scope", "estructura": "Structure",
        "sintesis": "Section synthesis", "publico": "Target audience",
        "resumen_ejecutivo": "Executive summary",
        "puntos_clave": "Key points", "terminos": "Technical terms / entities",
    },
}


def section_keys(template: str) -> list[str]:
    """Claves canónicas de las secciones de una plantilla (A/B/C)."""
    return list(_KEYS.get(template, _KEYS["C"]))


def section_names(template: str, lang: str = "pt") -> list[str]:
    """Etiquetas legibles de las secciones, en el idioma dado."""
    labels = _LABELS.get(lang, _LABELS["pt"])
    return [labels.get(k, k) for k in section_keys(template)]


def label(key: str, lang: str = "pt") -> str:
    return _LABELS.get(lang, _LABELS["pt"]).get(key, key)
