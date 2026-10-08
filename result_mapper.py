"""Transformación estricta del contrato remoto al documento BIREME."""

import re

MAPPING_VERSION = "1.0"
# Lista explícita: no convertir texto arbitrario en nombres de campos MongoDB.
LANGUAGES = {code: code for code in ("pt", "es", "en", "fr", "de", "it")}
LANGUAGES.update(
    por="pt", spa="es", eng="en", fra="fr", fre="fr", deu="de", ger="de", ita="it"
)


class MappingError(ValueError):
    """Resultado no publicable sin pérdida o inferencia de información."""


def language(value):
    if not isinstance(value, str) or value.strip().lower() not in LANGUAGES:
        raise MappingError("Idioma ausente o no admitido para un resumen presente")
    return LANGUAGES[value.strip().lower()]


def text_value(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise MappingError("El resumen debe ser un texto")
    return value if value.strip() else None


def map_result(
    result,
    *,
    source_id,
    source_collection,
    prefix,
    command="run",
    duplicate_policy="error",
):
    """Conserva textos completos; la única política actual de duplicados es error."""
    if duplicate_policy != "error":
        raise MappingError("Política de duplicados no admitida")
    if command != "run":
        raise MappingError("Publicación habilitada solamente para run")
    if (not isinstance(source_id, int) or isinstance(source_id, bool)) or not -(
        2**63
    ) <= source_id < 2**63:
        raise MappingError("Identificador original inválido")
    if not isinstance(prefix, str) or re.search(r"[\x00-\x1f]", prefix):
        raise MappingError("Prefijo inválido")
    if not isinstance(source_collection, str) or not source_collection:
        raise MappingError("Colección de origen ausente")
    if not isinstance(result, dict) or result.get("contract_version") != "2.0":
        raise MappingError("Se requiere el contrato 2.0 para publicar")
    document = {
        "id": f"{prefix}{source_id}",
        "meta": {
            "source_id": source_id,
            "source_collection": source_collection,
            "source_command": command,
            "contract_version": result["contract_version"],
            "mapping_version": MAPPING_VERSION,
        },
    }
    abstracts = result.get("ai_extracted_abstract")
    if abstracts is not None:
        if not isinstance(abstracts, list):
            raise MappingError("La lista de resúmenes extraídos es inválida")
        for abstract in abstracts:
            if not isinstance(abstract, dict):
                raise MappingError("Resumen extraído inválido")
            text = text_value(abstract.get("text"))
            if text is None:
                continue
            field = "ab_extracted_ia_" + language(abstract.get("lang"))
            if field in document:
                raise MappingError(
                    "Varios resúmenes del mismo idioma; publicación detenida"
                )
            document[field] = text
    generated = text_value(result.get("ai_generated_abstract"))
    if generated is not None:
        document["ab_created_ia_" + language(result.get("idioma_principal"))] = (
            generated
        )
    return document
