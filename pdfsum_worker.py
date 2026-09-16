#!/usr/bin/env python3
"""Orquestador para ejecutar comandos PDF remotos y persistir resultados."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.write_concern import WriteConcern

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
            values = open(args.ids_file, encoding="utf-8").read().split()
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
            "started_at": {"$lt": threshold},
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


def claim_job(jobs, identifier: int, command: str, max_attempts: int):
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
                "updated_at": now,
            },
            "$inc": {"attempts": 1},
            "$unset": {"result": "", "error": "", "finished_at": ""},
        },
        return_document=ReturnDocument.AFTER,
    )
    return document, token


def save_completed(jobs, identifier: int, command: str, token: str, result: Any) -> None:
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
                "status": "completed",
                "result": result,
                "updated_at": now,
                "finished_at": now,
            },
            "$unset": {"error": "", "claim_token": ""},
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
            "$unset": {"result": "", "claim_token": ""},
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
    url: str,
    connect_timeout: float,
    read_timeout: float,
) -> dict[str, Any]:
    """Llama de forma síncrona al procesamiento remoto."""
    response = session.post(
        endpoint,
        json={"id": identifier, "command": command, "url": url},
        timeout=(connect_timeout, read_timeout),
    )
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Servidor remoto devolvió una respuesta que no es JSON") from None

    if not isinstance(payload, dict):
        raise RuntimeError("Servidor remoto devolvió un JSON inválido")
    if payload.get("id") != identifier or payload.get("command") != command:
        raise RuntimeError("Servidor remoto devolvió una identidad o comando inesperado")

    if response.status_code == 200 and payload.get("status") == "completed":
        if "result" not in payload:
            raise RuntimeError("Servidor remoto no devolvió el resultado del procesamiento")
        return payload

    if payload.get("status") == "failed":
        return payload

    raise RuntimeError(f"Respuesta inesperada del servidor remoto (HTTP {response.status_code})")


def process_one(
    source,
    jobs,
    session: requests.Session,
    endpoint: str,
    identifier: int,
    command: str,
    *,
    max_attempts: int,
    connect_timeout: float,
    read_timeout: float,
) -> str:
    job, token = claim_job(jobs, identifier, command, max_attempts)
    if job is None:
        current = jobs.find_one({"id": identifier, "command": command}, {"status": 1})
        return current.get("status", "omitido") if current else "omitido"

    try:
        document = source.find_one(
            {"id": identifier}, {"_id": 0, "id": 1, "electronic_address": 1}
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

    try:
        payload = call_serveria(
            session,
            endpoint,
            identifier=identifier,
            command=command,
            url=url,
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
        save_completed(jobs, identifier, command, token, payload["result"])
        return "completed"

    # Servidor remoto ya sanitiza los detalles; aun así solo se conservan campos controlados.
    phase = payload.get("phase")
    if phase not in {"validacion", "descarga", "procesamiento", "limpieza"}:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orquesta jobs MongoDB y procesamiento síncrono en el servidor remoto"
    )
    parser.add_argument("--command", choices=COMMANDS, default="extract-abstracts")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--ids", nargs="+", help="IDs funcionales de mis")
    selection.add_argument("--ids-file", help="archivo UTF-8 con IDs")
    parser.add_argument(
        "--server-url",
        default=os.environ.get("PDFSUM_SERVER_URL"),
        help="base o endpoint del servidor remoto; también PDFSUM_SERVER_URL",
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--source-collection", default=DEFAULT_SOURCE_COLLECTION)
    parser.add_argument("--jobs-collection", default=DEFAULT_JOBS_COLLECTION)
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
        identifiers = load_ids(args)
        endpoint = normalize_endpoint(args.server_url)
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

    client = None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=10000)
        db = client[args.database]
        source = db[args.source_collection]
        jobs = db.get_collection(
            args.jobs_collection, write_concern=WriteConcern(w="majority")
        )
        jobs.create_index(
            [("id", 1), ("command", 1)], unique=True, name="id_command_unico"
        )

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
                    max_attempts=args.max_attempts,
                    connect_timeout=args.connect_timeout,
                    read_timeout=args.read_timeout,
                )
                totals[status] = totals.get(status, 0) + 1
                print(f"id={identifier} command={args.command} status={status}")

        print("resumen:", " ".join(f"{key}={value}" for key, value in sorted(totals.items())))
        return 1 if totals.get("failed", 0) else 0

    except PyMongoError:
        print("ERROR: fallo de infraestructura MongoDB", file=sys.stderr)
        return 2
    except Exception as exc:
        # No imprimir detalles de drivers, URLs ni respuestas remotas por seguridad.
        print(f"ERROR: fallo de ejecución ({type(exc).__name__})", file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
