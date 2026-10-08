"""Publicación recuperable, sin transacciones ni llamadas al procesamiento remoto."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from bson import BSON
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from result_mapper import MappingError, map_result

# Reserva para metadatos operacionales y futuras actualizaciones del job.
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024 - 64 * 1024


def check_size(document):
    if len(BSON.encode(document)) > MAX_DOCUMENT_BYTES:
        raise MappingError("El documento supera el límite BSON con margen operacional")


def publish(jobs, results, identity, config):
    """Reintenta desde result; un token protege la confirmación del intento."""
    now = datetime.now(timezone.utc)
    token = uuid4().hex
    job = jobs.find_one_and_update(
        {
            **identity,
            "status": "completed",
            "$or": [
                {"publication.status": {"$in": ["pending", "failed"]}},
                {
                    "publication.status": "publishing",
                    "publication.lease_until": {"$lt": now},
                },
            ],
        },
        {
            "$set": {
                "publication.status": "publishing",
                "publication.token": token,
                "publication.lease_until": now + timedelta(minutes=5),
            },
            "$inc": {"publication.attempts": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if job is None:
        current = jobs.find_one(identity) or {}
        return current.get("publication", {}).get("status", "pending")
    publication = job["publication"]
    status = "published"
    error = None
    try:
        if not isinstance(publication.get("version"), datetime):
            raise MappingError(
                "Falta una fecha de procesamiento válida para ordenar la publicación"
            )
        if publication["config"] != config:
            raise MappingError(
                "La configuración difiere del destino persistido del job"
            )
        document = map_result(
            job["result"],
            source_id=job["id"],
            command=job["command"],
            source_collection=config["source_collection"],
            prefix=config["prefix"],
        )
        document["meta"].update(
            source_version=publication["version"], revision=publication["revision"]
        )
        check_size(document)
        # El índice único convierte una carrera con una versión más reciente en
        # DuplicateKeyError; nunca se sustituye incondicionalmente por id.
        try:
            results.replace_one(
                {
                    "id": document["id"],
                    "$or": [
                        {"meta.source_version": {"$lt": publication["version"]}},
                        {
                            "meta.source_version": publication["version"],
                            "meta.revision": publication["revision"],
                        },
                        {"meta.source_version": {"$exists": False}},
                    ],
                },
                document,
                upsert=True,
            )
        except DuplicateKeyError:
            current = results.find_one({"id": document["id"]})
            if (
                current
                and current.get("meta", {}).get(
                    "source_version", publication["version"]
                )
                > publication["version"]
            ):
                status = "superseded"
            else:
                raise MappingError(
                    "Conflicto de versión en el documento publicado"
                ) from None
    except MappingError as exc:
        status, error = "failed", str(exc)
    except (PyMongoError, ValueError, OverflowError):
        status, error = "failed", "No se pudo persistir la publicación en MongoDB"
    changes = {
        "publication.status": status,
        "publication.updated_at": datetime.now(timezone.utc),
    }
    if error:
        changes["publication.error"] = error
    saved = jobs.update_one(
        {**identity, "publication.token": token},
        {
            "$set": changes,
            "$unset": {
                "publication.token": "",
                "publication.lease_until": "",
                **({} if error else {"publication.error": ""}),
            },
        },
    )
    return status if saved.matched_count else "pending"
