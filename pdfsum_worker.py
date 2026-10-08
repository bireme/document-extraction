#!/usr/bin/env python3
"""Orquestador para ejecutar comandos PDF remotos y persistir resultados."""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from bson.errors import InvalidDocument
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.write_concern import WriteConcern

from result_mapper import MappingError
from result_publication import check_size, publish

COMMANDS = ("extract-abstracts", "transcribe", "run")
DEFAULT_DATABASE = "FIs_02_converted"
DEFAULT_SOURCE_COLLECTION = "mis"
DEFAULT_JOBS_COLLECTION = "document_extraction_jobs"


class SelectionError(ValueError):
    """Fallo controlado al localizar la entrada o seleccionar su PDF."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def heartbeat(jobs, identifier, command, token, stale_after):
    """Renueva la reserva mientras se espera al servidor remoto."""
    stop = Event()

    def renew():
        while not stop.wait(min(30, stale_after.total_seconds() / 3)):
            try:
                updated = jobs.update_one(
                    {
                        "id": identifier,
                        "command": command,
                        "status": "processing",
                        "claim_token": token,
                    },
                    {"$set": {"lease_until": utcnow() + stale_after}},
                )
                if not updated.matched_count:
                    return
            except PyMongoError:
                # No revelar detalles del driver; el token impide guardar tras perder el claim.
                return

    thread = Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


def select_pdf(document: dict[str, Any] | None) -> str:
    """Selecciona una URL PDF de electronic_address, prefiriendo HTTPS."""
    if document is None:
        raise SelectionError("id_inexistente", "No se encontró el ID solicitado")

    addresses = document.get("electronic_address")
    if not isinstance(addresses, list) or not addresses:
        raise SelectionError("sin_recurso", "No hay direcciones electrónicas")

    candidates: list[tuple[bool, str]] = []
    for entry in addresses:
        value = entry.get("_u") if isinstance(entry, dict) else None
        if not isinstance(value, str):
            continue
        if re.search(r"[\s\\\x00-\x1f\x7f]|%(?![0-9a-fA-F]{2})", value):
            continue
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme in {"http", "https"}
                and value.lower().startswith(("http://", "https://"))
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and (parsed.port is None or 0 < parsed.port <= 65535)
                and parsed.path.lower().endswith(".pdf")
            ):
                candidates.append((parsed.scheme != "https", value))
        except ValueError:
            continue

    if not candidates:
        raise SelectionError("sin_pdf", "No hay una URL PDF utilizable")

    # min conserva el primer candidato en empates y prioriza HTTPS.
    return min(candidates, key=lambda candidate: candidate[0])[1]


def parse_ids(values: list[str]) -> list[int]:
    """Valida IDs funcionales como enteros BSON de 64 bits, sin duplicados."""
    identifiers: list[int] = []
    for value in values:
        if not re.fullmatch(r"-?[0-9]+", value):
            raise ValueError("Los IDs deben ser enteros BSON de 64 bits")
        identifier = int(value)
        if not -(2**63) <= identifier < 2**63:
            raise ValueError("Los IDs deben ser enteros BSON de 64 bits")
        identifiers.append(identifier)
    return list(dict.fromkeys(identifiers))


def load_ids(args: argparse.Namespace) -> list[int]:
    if bool(args.ids) == bool(args.ids_file):
        raise ValueError("Indique exactamente una selección: --ids o --ids-file")
    if args.ids_file:
        try:
            with open(args.ids_file, encoding="utf-8") as file:
                values = file.read().split()
        except (OSError, UnicodeError):
            raise ValueError("No se pudo leer el archivo de IDs") from None
    else:
        values = args.ids
    if not values:
        raise ValueError("La selección de IDs debe contener al menos un ID")
    return parse_ids(values)


def prepare_job(jobs, identifier: int, command: str) -> None:
    """Crea el job si todavía no existe, sin alterar uno ya procesado."""
    now = utcnow()
    identity = {"id": identifier, "command": command}
    try:
        jobs.update_one(
            identity,
            {
                "$setOnInsert": {
                    **identity,
                    "status": "pending",
                    "attempts": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
    except DuplicateKeyError:
        # Otra instancia pudo crear el mismo job al mismo tiempo.
        pass


def recover_stale_job(
    jobs,
    identifier: int,
    command: str,
    *,
    stale_after: timedelta,
) -> bool:
    """Devuelve a pending un processing abandonado hace demasiado tiempo."""
    threshold = utcnow() - stale_after
    result = jobs.update_one(
        {
            "id": identifier,
            "command": command,
            "status": "processing",
            "$or": [
                {"lease_until": {"$lt": utcnow()}},
                {"lease_until": {"$exists": False}, "started_at": {"$lt": threshold}},
            ],
        },
        {
            "$set": {
                "status": "pending",
                "updated_at": utcnow(),
                "recovered_at": utcnow(),
            },
            "$unset": {"claim_token": ""},
        },
    )
    return result.modified_count == 1


def claim_job(
    jobs,
    identifier: int,
    command: str,
    max_attempts: int,
    stale_after: timedelta = timedelta(minutes=60),
):
    """Reclama un job pending/failed de forma atómica."""
    token = uuid4().hex
    now = utcnow()
    document = jobs.find_one_and_update(
        {
            "id": identifier,
            "command": command,
            "status": {"$in": ["pending", "failed"]},
            "attempts": {"$lt": max_attempts},
        },
        {
            "$set": {
                "status": "processing",
                "claim_token": token,
                "started_at": now,
                "lease_until": now + stale_after,
                "updated_at": now,
            },
            "$inc": {"attempts": 1},
            "$unset": {"result": "", "error": "", "finished_at": ""},
        },
        return_document=ReturnDocument.AFTER,
    )
    return document, token


def save_completed(
    jobs, identifier: int, command: str, token: str, result: Any, publication=None
) -> None:
    now = utcnow()
    check_size({"result": result, "publication": publication})
    saved = jobs.update_one(
        {
            "id": identifier,
            "command": command,
            "claim_token": token,
            "status": "processing",
        },
        {
            "$set": {
                "status": "completed",
                "result": result,
                "publication": publication or {"status": "disabled"},
                "updated_at": now,
                "finished_at": now,
            },
            "$unset": {"error": "", "claim_token": "", "lease_until": ""},
        },
    )
    if saved.matched_count != 1:
        raise RuntimeError("La reserva del job ya no está vigente")


def save_failed(
    jobs,
    identifier: int,
    command: str,
    token: str,
    *,
    phase: str,
    code: str,
    message: str,
) -> None:
    now = utcnow()
    saved = jobs.update_one(
        {
            "id": identifier,
            "command": command,
            "claim_token": token,
            "status": "processing",
        },
        {
            "$set": {
                "status": "failed",
                "error": {"phase": phase, "code": code, "message": message},
                "updated_at": now,
                "finished_at": now,
            },
            "$unset": {"result": "", "claim_token": "", "lease_until": ""},
        },
    )
    if saved.matched_count != 1:
        raise RuntimeError("La reserva del job ya no está vigente")


def call_serveria(
    session: requests.Session,
    endpoint: str,
    *,
    identifier: int,
    command: str,
    url: str | None = None,
    folder: str | None = None,
    connect_timeout: float,
    read_timeout: float,
) -> dict[str, Any]:
    """Llama de forma síncrona al procesamiento remoto."""
    request_body: dict[str, Any] = {
        "id": identifier,
        "command": command,
    }

    if url is not None:
        request_body["url"] = url
    elif folder is not None:
        request_body["folder"] = folder
    else:
        raise RuntimeError("No se definió una fuente de PDF")
    response = session.post(
        endpoint,
        json=request_body,
        timeout=(connect_timeout, read_timeout),
    )
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(
            "Servidor remoto devolvió una respuesta que no es JSON"
        ) from None

    if not isinstance(payload, dict):
        raise RuntimeError("Servidor remoto devolvió un JSON inválido")  # noqa: TRY004
    if payload.get("id") != identifier or payload.get("command") != command:
        raise RuntimeError(
            "Servidor remoto devolvió una identidad o comando inesperado"
        )

    if response.status_code == 200 and payload.get("status") == "completed":
        if "result" not in payload:
            raise RuntimeError(
                "Servidor remoto no devolvió el resultado del procesamiento"
            )
        return payload

    if payload.get("status") == "failed":
        return payload

    raise RuntimeError(
        f"Respuesta inesperada del servidor remoto (HTTP {response.status_code})"
    )


def process_one(
    source,
    jobs,
    session: requests.Session,
    endpoint: str,
    identifier: int,
    command: str,
    *,
    input_mode: str,
    input_folder: str | None,
    max_attempts: int,
    connect_timeout: float,
    read_timeout: float,
    results=None,
    publication_config=None,
    stale_after: timedelta = timedelta(minutes=60),
) -> str:
    job, token = claim_job(jobs, identifier, command, max_attempts, stale_after)
    if job is None:
        current = jobs.find_one({"id": identifier, "command": command})
        if (
            current
            and current.get("status") == "completed"
            and results is not None
            and command == "run"
        ):
            return publication_status(jobs, results, current, publication_config)
        return current.get("status", "omitido") if current else "omitido"
    url = None
    folder = None

    if input_mode == "url":
        try:
            document = source.find_one(
                {"id": identifier},
                {"_id": 0, "id": 1, "electronic_address": 1},
            )
            url = select_pdf(document)
        except SelectionError as exc:
            save_failed(
                jobs,
                identifier,
                command,
                token,
                phase="seleccion",
                code=exc.code,
                message=str(exc),
            )
            return "failed"
    else:
        folder = input_folder
    try:
        with heartbeat(jobs, identifier, command, token, stale_after):
            payload = call_serveria(
                session,
                endpoint,
                identifier=identifier,
                command=command,
                url=url,
                folder=folder,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            )
    except requests.RequestException:
        save_failed(
            jobs,
            identifier,
            command,
            token,
            phase="comunicacion",
            code="serveria_no_disponible",
            message="No se pudo completar la comunicación con el servidor remoto",
        )
        return "failed"
    except RuntimeError:
        save_failed(
            jobs,
            identifier,
            command,
            token,
            phase="comunicacion",
            code="respuesta_invalida",
            message="Servidor remoto devolvió una respuesta inválida",
        )
        return "failed"

    if payload["status"] == "completed":
        publication = (
            make_publication(job, publication_config)
            if command == "run" and results is not None
            else None
        )
        try:
            save_completed(
                jobs, identifier, command, token, payload["result"], publication
            )
        except (MappingError, InvalidDocument, OverflowError):
            save_failed(
                jobs,
                identifier,
                command,
                token,
                phase="persistencia",
                code="resultado_bson_excedido",
                message="Resultado no almacenable dentro del límite BSON",
            )
            return "failed"
        if publication:
            return publication_status(
                jobs, results, {**job, "publication": publication}, publication_config
            )
        return "completed"

    # Servidor remoto ya sanitiza los detalles; aun así solo se conservan campos controlados.
    phase = payload.get("phase")
    if phase not in {
        "validacion",
        "seleccion",
        "descarga",
        "procesamiento",
        "limpieza",
    }:
        phase = "procesamiento"
    error_type = payload.get("error_type")
    if not isinstance(error_type, str) or not error_type:
        error_type = "entrada_fallida"
    message = payload.get("error")
    if not isinstance(message, str) or not message:
        message = "Falló el procesamiento remoto"

    save_failed(
        jobs,
        identifier,
        command,
        token,
        phase=phase,
        code=error_type[:120],
        message=message[:500],
    )
    return "failed"


def make_publication(job, config):
    return {
        "status": "pending",
        "attempts": 0,
        "config": config,
        "version": job.get("started_at", job.get("finished_at")),
        "revision": uuid4().hex,
    }


def publication_status(jobs, results, job, config):
    identity = {"id": job["id"], "command": job["command"]}
    if "publication" not in job:
        # Compatibilidad con originales completados antes de introducir publicación.
        jobs.update_one(
            {**identity, "status": "completed", "publication": {"$exists": False}},
            {"$set": {"publication": make_publication(job, config)}},
        )
    status = publish(jobs, results, identity, config)
    return (
        "completed"
        if status in {"published", "superseded"}
        else "publication_" + status
    )


def collections_config(args):
    source_db = args.source_database or args.database or DEFAULT_DATABASE
    jobs_db = args.jobs_database or args.database or DEFAULT_DATABASE
    results_db = args.results_database or "Enrichment_IA"
    locations = [
        (source_db, args.source_collection),
        (jobs_db, args.jobs_collection),
        (results_db, args.results_collection),
    ]
    if len(set(locations)) != 3:
        raise ValueError("Origen, jobs y resultados deben ser colecciones diferentes")
    return locations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orquesta jobs MongoDB y procesamiento síncrono en el servidor remoto"
    )
    parser.add_argument("--command", choices=COMMANDS, default="extract-abstracts")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--retry-publications",
        action="store_true",
        help="publicar originales guardados sin invocar la API",
    )
    selection.add_argument("--ids", nargs="+", help="IDs funcionales de mis")
    selection.add_argument("--ids-file", help="archivo UTF-8 con IDs")
    parser.add_argument(
        "--server-url",
        default=os.environ.get("PDFSUM_SERVER_URL"),
        help="base o endpoint del servidor remoto; también PDFSUM_SERVER_URL",
    )
    parser.add_argument(
        "--input-mode",
        choices=("url", "folder"),
        default=os.environ.get("PDFSUM_INPUT_MODE", "url"),
        help="origen del PDF: url o folder; también PDFSUM_INPUT_MODE",
    )
    parser.add_argument(
        "--input-folder",
        default=os.environ.get("PDFSUM_INPUT_FOLDER"),
        help="carpeta remota usada cuando input-mode=folder; también PDFSUM_INPUT_FOLDER",
    )
    parser.add_argument(
        "--database",
        help="base heredada para origen y jobs, si no se especifican por separado",
    )
    for option in ("source-database", "jobs-database", "results-database"):
        parser.add_argument(
            "--" + option,
            default=os.environ.get("PDFSUM_" + option.upper().replace("-", "_")),
        )
    for option, default in (
        ("source-collection", DEFAULT_SOURCE_COLLECTION),
        ("jobs-collection", DEFAULT_JOBS_COLLECTION),
        ("results-collection", "document_abstracts"),
        ("result-id-prefix", ""),
        ("result-format", "bireme"),
    ):
        parser.add_argument(
            "--" + option,
            default=os.environ.get(
                "PDFSUM_" + option.upper().replace("-", "_"), default
            ),
        )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument(
        "--stale-after-minutes",
        type=int,
        default=60,
        help="recuperar processing abandonados después de este tiempo",
    )
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=1800.0,
        help="timeout de espera del procesamiento remoto, en segundos",
    )
    return parser


def normalize_endpoint(value: str | None) -> str:
    if not value or not value.strip():
        raise ValueError("Falta --server-url o PDFSUM_SERVER_URL")
    value = value.rstrip("/")
    if value.endswith("/api/pdfsum"):
        return value
    return value + "/api/pdfsum"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        identifiers = [] if args.retry_publications else load_ids(args)
        endpoint = (
            "" if args.retry_publications else normalize_endpoint(args.server_url)
        )
        locations = collections_config(args)
        if args.result_format != "bireme":
            raise ValueError("PDFSUM_RESULT_FORMAT debe ser bireme")
        if any(
            not math.isfinite(t) or t <= 0
            for t in (args.connect_timeout, args.read_timeout)
        ):
            raise ValueError("Los timeouts deben ser positivos y finitos")
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    uri = os.environ.get("PDFSUM_MONGODB_URI")
    if not uri:
        print("ERROR: falta PDFSUM_MONGODB_URI", file=sys.stderr)
        return 2
    if args.max_attempts < 1:
        print("ERROR: --max-attempts debe ser al menos 1", file=sys.stderr)
        return 2
    if args.stale_after_minutes < 1:
        print("ERROR: --stale-after-minutes debe ser al menos 1", file=sys.stderr)
        return 2
    if (
        not args.retry_publications
        and args.input_mode == "folder"
        and not args.input_folder
    ):
        print(
            "ERROR: falta --input-folder o PDFSUM_INPUT_FOLDER",
            file=sys.stderr,
        )
        return 2

    client = None
    try:
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=30000,
            tz_aware=True,
        )
        source = client[locations[0][0]][locations[0][1]]
        jobs = client[locations[1][0]].get_collection(
            locations[1][1], write_concern=WriteConcern(w="majority")
        )
        results = client[locations[2][0]].get_collection(
            locations[2][1], write_concern=WriteConcern(w="majority")
        )
        publication_config = {
            "database": locations[2][0],
            "collection": locations[2][1],
            "source_collection": args.source_collection,
            "source_database": locations[0][0],
            "prefix": args.result_id_prefix,
            "format": args.result_format,
        }
        jobs.create_index(
            [("id", 1), ("command", 1)], unique=True, name="id_command_unico"
        )

        results.create_index([("id", 1)], unique=True, name="id_publicacion_unico")
        if args.retry_publications:
            failed = False
            for job in jobs.find(
                {
                    "status": "completed",
                    "command": "run",
                    "$or": [
                        {
                            "publication.status": {
                                "$in": ["pending", "failed", "publishing"]
                            }
                        },
                        {"publication": {"$exists": False}},
                    ],
                }
            ):
                status = publication_status(jobs, results, job, publication_config)
                print(f"id={job['id']} command=run status={status}")
                failed = failed or status != "completed"
            return 1 if failed else 0

        for identifier in identifiers:
            prepare_job(jobs, identifier, args.command)
            if recover_stale_job(
                jobs,
                identifier,
                args.command,
                stale_after=timedelta(minutes=args.stale_after_minutes),
            ):
                print(f"id={identifier} recuperado de processing abandonado")

        totals: dict[str, int] = {}
        with requests.Session() as session:
            for identifier in identifiers:
                status = process_one(
                    source,
                    jobs,
                    session,
                    endpoint,
                    identifier,
                    args.command,
                    input_mode=args.input_mode,
                    input_folder=args.input_folder,
                    max_attempts=args.max_attempts,
                    connect_timeout=args.connect_timeout,
                    read_timeout=args.read_timeout,
                    results=results,
                    publication_config=publication_config,
                    stale_after=timedelta(minutes=args.stale_after_minutes),
                )
                totals[status] = totals.get(status, 0) + 1
                print(f"id={identifier} command={args.command} status={status}")

        print(
            "resumen:",
            " ".join(f"{key}={value}" for key, value in sorted(totals.items())),
        )
        return 1 if any(key not in {"completed"} for key in totals) else 0

    except PyMongoError:
        print("ERROR: fallo de infraestructura MongoDB", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - Frontera CLI: no revelar secretos.
        # No imprimir detalles de drivers, URLs ni respuestas remotas por seguridad.
        print(f"ERROR: fallo de ejecución ({type(exc).__name__})", file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
