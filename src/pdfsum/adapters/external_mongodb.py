"""Fuente de solo lectura en mis y jobs operacionales separados en MongoDB."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from ..external import INPUT_TYPES, ExternalInput, ExternalResult


class MongoInfrastructureError(RuntimeError):
    """Fallo de almacenamiento cuyo detalle original nunca se publica."""


class MongoSelectionError(ValueError):
    """Error de una entrada, con código y mensaje controlados por el adapter."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _select_pdf(document):
    if document is None:
        raise MongoSelectionError("id_inexistente", "No se encontró el ID solicitado")
    addresses = document.get("electronic_address")
    if not isinstance(addresses, list) or not addresses:
        raise MongoSelectionError("sin_recurso", "No hay direcciones electrónicas")
    candidates = []
    for entry in addresses:
        value = entry.get("_u") if isinstance(entry, dict) else None
        if not isinstance(value, str) or re.search(
            r"[\s\\\x00-\x1f\x7f]|%(?![0-9a-fA-F]{2})", value
        ):
            continue
        try:
            url = urlsplit(value)
            if (
                url.scheme in {"http", "https"}
                and value.lower().startswith(("http://", "https://"))
                and url.hostname
                and url.username is None
                and url.password is None
                and (url.port is None or 0 < url.port <= 65535)
                and url.path.lower().endswith(".pdf")
            ):
                candidates.append((url.scheme != "https", value))
        except ValueError:
            continue
    if not candidates:
        raise MongoSelectionError("sin_pdf", "No hay una URL PDF utilizable")
    # min conserva el primer elemento en empates; no altera la URL ni descubre enlaces.
    return min(candidates, key=lambda candidate: candidate[0])[1]


def _selected_ids(config):
    values, filename = config.get("ids"), config.get("ids_file")
    if bool(values) == bool(filename):
        raise ValueError("Indique exactamente una selección: --ids o --ids-file")
    if filename:
        try:
            values = Path(filename).read_text(encoding="utf-8").split()
        except (OSError, UnicodeError, TypeError, ValueError):
            raise ValueError("No se pudo leer el archivo de IDs") from None
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("La selección de IDs debe contener al menos un ID")
    identifiers = []
    for value in values:
        if type(value) is int:
            identifier = value
        elif isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
            try:
                identifier = int(value)
            except ValueError:
                raise ValueError("Los IDs deben ser enteros BSON de 64 bits") from None
        else:
            raise ValueError("Los IDs deben ser enteros BSON de 64 bits")
        if not -(2**63) <= identifier < 2**63:
            raise ValueError("Los IDs deben ser enteros BSON de 64 bits")
        identifiers.append(identifier)
    return list(dict.fromkeys(identifiers))


class MongoJobs:
    """Implementa fuente/store compartiendo las reservas, sin modificar el motor.

    Los errores de selección se persisten aquí y se cuentan por separado, pues no
    hay recurso que entregar al executor. processing no caduca automáticamente.
    """

    def __init__(self, source, jobs, ids, *, duplicate_key_error, client=None):
        self.source = source
        self.jobs = jobs
        self.ids = ids
        self.duplicate_key_error = duplicate_key_error
        self.client = client
        self.claims = {}
        self.selection_failures = 0

    def close(self):
        try:
            if self.client is not None:
                self.client.close()
        except Exception:  # noqa: BLE001 — sanitizar errores del driver
            raise MongoInfrastructureError(
                "No se pudo cerrar el acceso a MongoDB"
            ) from None

    def pending(self, command):
        if command == "summarize":
            raise ValueError(
                "MongoDB summarize no está disponible: mis no tiene una fuente "
                "identificada de texto transcrito"
            )
        if command not in INPUT_TYPES:
            raise ValueError("Comando externo no admitido")
        self.selection_failures = 0
        try:
            self.jobs.create_index(
                [("id", 1), ("command", 1)], unique=True, name="id_command_unico"
            )
            for identifier in self.ids:
                identity = {"id": identifier, "command": command}
                now = datetime.now(timezone.utc)
                try:
                    self.jobs.update_one(
                        identity,
                        {
                            "$setOnInsert": {
                                **identity,
                                "status": "pending",
                                "created_at": now,
                                "updated_at": now,
                                "attempts": 0,
                            }
                        },
                        upsert=True,
                    )
                except self.duplicate_key_error:
                    # Otra ejecución pudo insertar la misma identidad concurrentemente.
                    if self.jobs.find_one(identity) is None:
                        raise
                token = uuid4().hex
                claimed = self.jobs.find_one_and_update(
                    {**identity, "status": {"$in": ["pending", "failed"]}},
                    {
                        "$set": {
                            "status": "processing",
                            "claim_token": token,
                            "started_at": now,
                            "updated_at": now,
                        },
                        "$inc": {"attempts": 1},
                        "$unset": {"result": "", "error": "", "finished_at": ""},
                    },
                    return_document=True,  # ReturnDocument.AFTER, sin importar pymongo aquí.
                )
                if claimed is None:
                    continue
                self.claims[(identifier, command)] = token
                # Nunca se consulta por _id ni se escribe/crea índices en la fuente.
                document = self.source.find_one(
                    {"id": identifier}, {"id": 1, "electronic_address": 1}
                )
                try:
                    url = _select_pdf(document)
                except MongoSelectionError as exc:
                    self.save(
                        ExternalResult(
                            identifier,
                            command,
                            "failed",
                            phase="seleccion",
                            error_type=exc.code,
                            error=str(exc),
                        )
                    )
                    self.selection_failures += 1
                    continue
                yield ExternalInput(identifier, "pdf", url)
        except Exception:  # noqa: BLE001 — sanitizar errores del driver
            raise MongoInfrastructureError(
                "No se pudo seleccionar o reservar el trabajo en MongoDB"
            ) from None

    def save(self, result):
        try:
            token = self.claims[(result.id, result.command)]
            if result.status not in {"completed", "failed"}:
                raise ValueError("Estado de resultado no admitido")
            now = datetime.now(timezone.utc)
            fields = {"status": result.status, "updated_at": now, "finished_at": now}
            if result.status == "completed":
                fields["result"] = result.result
                remove = "error"
            else:
                # No se confía en mensajes de excepciones ni de stores externos.
                selection_messages = {
                    "id_inexistente": "No se encontró el ID solicitado",
                    "sin_recurso": "No hay direcciones electrónicas",
                    "sin_pdf": "No hay una URL PDF utilizable",
                }
                phase = (
                    result.phase
                    if result.phase
                    in {"seleccion", "validacion", "materializacion", "procesamiento"}
                    else "procesamiento"
                )
                code = (
                    result.error_type
                    if phase == "seleccion" and result.error_type in selection_messages
                    else "entrada_fallida"
                )
                fields["error"] = {
                    "phase": phase,
                    "code": code,
                    "message": selection_messages.get(
                        code, "Falló la entrada; detalle omitido por privacidad"
                    ),
                }
                remove = "result"
            saved = self.jobs.update_one(
                {
                    "id": result.id,
                    "command": result.command,
                    "claim_token": token,
                    "status": "processing",
                },
                {"$set": fields, "$unset": {remove: ""}},
            )
            if (
                saved.matched_count != 1
                and self.jobs.find_one(
                    {
                        "id": result.id,
                        "command": result.command,
                        "claim_token": token,
                        "status": result.status,
                    }
                )
                is None
            ):
                raise ValueError("Reserva no vigente")
        except Exception:  # noqa: BLE001 — sanitizar errores del driver
            raise MongoInfrastructureError(
                "No se pudo persistir el trabajo en MongoDB"
            ) from None


def build_mongodb_provider(config: dict):
    """Carga pymongo únicamente al seleccionar MongoDB; URI solo del entorno."""
    if config.get("command") == "summarize":
        raise ValueError(
            "MongoDB summarize no está disponible: mis no tiene una fuente "
            "identificada de texto transcrito"
        )
    ids = _selected_ids(config)
    database = config.get("database", "FIs_02_converted")
    source_name = config.get("source_collection", "mis")
    jobs_name = config.get("jobs_collection", "document_extraction_jobs")
    if any(
        not isinstance(name, str) or not name
        for name in (database, source_name, jobs_name)
    ):
        raise ValueError("Base y colecciones deben tener nombres no vacíos")
    if jobs_name == source_name or jobs_name == "mis":
        raise ValueError("La colección de jobs debe ser distinta de la fuente y de mis")
    if "uri" in config or "mongodb_uri" in config:
        raise ValueError("La URI MongoDB solo se admite en PDFSUM_MONGODB_URI")
    uri = os.environ.get("PDFSUM_MONGODB_URI")
    if not uri:
        raise ValueError("Falta la variable de entorno PDFSUM_MONGODB_URI")
    try:
        from pymongo import MongoClient
        from pymongo.errors import DuplicateKeyError
        from pymongo.write_concern import WriteConcern
    except ImportError:
        raise ValueError(
            "El provider MongoDB requiere la dependencia opcional pymongo; "
            "instale pdfsum[mongodb]"
        ) from None
    client = None
    try:
        # Confirmación mayoritaria incluso si la URI pide escrituras sin confirmar.
        client = MongoClient(uri, connect=False, serverSelectionTimeoutMS=10000)
        db = client[database]
        adapter = MongoJobs(
            db[source_name],
            db.get_collection(jobs_name, write_concern=WriteConcern(w="majority")),
            ids,
            duplicate_key_error=DuplicateKeyError,
            client=client,
        )
        return adapter, adapter
    except Exception:  # noqa: BLE001 — sanitizar errores del driver
        try:
            if client is not None:
                client.close()
        finally:
            raise MongoInfrastructureError(
                "No se pudo configurar el acceso a MongoDB"
            ) from None
