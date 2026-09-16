"""API síncrona de comandos PDF; la identidad externa nunca determina rutas."""

import json
import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, get_args
from uuid import uuid4

from ..abstract_refine import ABSTRACT_REFINE_CONTEXT_CHARS
from ..workspace import Workspace
from .abstract_batch import extract_abstracts_from_pdfs
from .observability import EventLog
from .pdf_batch import run_batch_pdfs, transcribe_pdfs
from .pdf_download import PDFDownloader, validate_pdf_url

PROCESSING_ERROR = "Fallo del procesamiento; detalle omitido"

PDFCommand = Literal["extract-abstracts", "transcribe", "run"]


def process_pdf(
    pdf: Path,
    workspace: Workspace,
    transcriber,
    llm,
    *,
    command: PDFCommand,
    context_chars: int = ABSTRACT_REFINE_CONTEXT_CHARS,
    backend: str | None = None,
    model: str | None = None,
    long_strategy: str = "excerpt",
) -> dict | str:
    """Despacha funciones Python y devuelve el artefacto principal sin transformarlo."""

    def safe_error(_exc):
        return PROCESSING_ERROR

    if command == "extract-abstracts":
        extract_abstracts_from_pdfs(
            str(pdf.parent),
            workspace,
            transcriber,
            llm,
            context_chars=context_chars,
            backend=backend,
            model=model,
            format_error=safe_error,
        )
        output = workspace.abstract_path(pdf.stem)
    elif command == "transcribe":
        transcribe_pdfs(str(pdf.parent), workspace, transcriber)
        return workspace.ocr_path(pdf.stem).read_text(encoding="utf-8")
    elif command == "run":
        report = run_batch_pdfs(
            str(pdf.parent),
            workspace,
            transcriber,
            llm,
            long_strategy=long_strategy,
            format_error=safe_error,
        )
        if report["progress"]["failed"]:
            raise RuntimeError(PROCESSING_ERROR)
        output = workspace.summary_path(pdf.stem)
    else:
        raise ValueError("Comando PDF no permitido")
    return json.loads(output.read_text(encoding="utf-8"))


def create_app(
    workspace: str | Path,
    *,
    processor: Callable[[Path, Workspace, PDFCommand], dict | str],
    logs_dir: str | Path | None = None,
    downloader: PDFDownloader | None = None,
):
    """Crea un servicio independiente, sin almacén de jobs ni acceso a bases de datos."""
    try:
        from fastapi import Body, FastAPI
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
    except ImportError:
        raise RuntimeError(
            "Instala el extra opcional: pip install 'pdfsum[service]'"
        ) from None

    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    downloader = downloader or PDFDownloader()
    logger = logging.getLogger(__name__)
    app = FastAPI(title="Procesamiento de PDFs")

    def failure(identity, command, phase, error_type, message, code):
        return JSONResponse(
            status_code=code,
            content={
                "id": identity,
                "command": command,
                "status": "failed",
                "phase": phase,
                "error_type": error_type,
                "error": message,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_json(request, exc):
        identity = exc.body.get("id") if isinstance(exc.body, dict) else None
        return failure(
            identity, None, "validacion", "ValidationError", "JSON inválido", 422
        )

    @app.post("/api/pdfsum")
    def process(body: Any = Body(default=None)):  # noqa: B008 — declaración de FastAPI
        identity = body.get("id") if isinstance(body, dict) else None
        raw_command = body.get("command") if isinstance(body, dict) else None
        command = raw_command if raw_command in get_args(PDFCommand) else None
        valid_id = (type(identity) is int and identity > 0) or (
            isinstance(identity, str)
            and 0 < len(identity) <= 256
            and bool(identity.strip())
            and not any(ord(c) < 32 or ord(c) == 127 for c in identity)
        )
        if not valid_id:
            return failure(
                identity,
                command,
                "validacion",
                "ValidationError",
                "id debe ser un entero positivo o texto no vacío de hasta 256 caracteres",
                422,
            )
        if set(body) != {"id", "command", "url"} or command is None:
            return failure(
                identity,
                command,
                "validacion",
                "ValidationError",
                "La solicitud debe contener id, command y url; command admite extract-abstracts, transcribe o run",
                422,
            )
        try:
            validate_pdf_url(body["url"])
        except (ValueError, TypeError):
            return failure(
                identity,
                command,
                "validacion",
                "ValidationError",
                "URL HTTP inválida o destino no permitido",
                422,
            )

        run_id = uuid4().hex
        started = time.perf_counter()
        phase = "procesamiento"
        temporary = None
        events = None

        def emit(event, **fields):
            logger.info(
                "Procesamiento HTTP: %s (%s, %s)", event, run_id, command, extra=fields
            )
            if events is not None:
                try:
                    events.write(event, command=command, **fields)
                except OSError:
                    logger.warning("No se pudo escribir el evento HTTP (%s)", run_id)

        try:
            temporary = tempfile.TemporaryDirectory(
                prefix=f"pdfsum-{run_id}-", dir=root
            )
            execution = Path(temporary.name)
            logs = (
                Path(logs_dir) / run_id if logs_dir is not None else execution / "logs"
            )
            events = EventLog(logs / "api-events.jsonl", run_id)
            ws = Workspace(execution, logs_dir=logs)
            inputs = execution / "input"
            inputs.mkdir()
            pdf = inputs / f"{run_id}.pdf"
            phase = "descarga"
            emit("phase_started", phase=phase)
            downloader.download(body["url"], pdf)
            phase = "procesamiento"
            emit("phase_started", phase=phase)
            result = processor(pdf, ws, command)
            response = JSONResponse(
                {
                    "id": identity,
                    "command": command,
                    "status": "completed",
                    "result": result,
                }
            )
        except Exception:  # noqa: BLE001 — frontera HTTP sin detalles internos
            error_type = "DownloadError" if phase == "descarga" else "ProcessingError"
            emit("phase_failed", phase=phase, error_type=error_type)
            response = failure(
                identity,
                command,
                phase,
                error_type,
                "No se pudo descargar el PDF"
                if phase == "descarga"
                else "No se pudo procesar el PDF",
                502 if phase == "descarga" else 500,
            )
        finally:
            if temporary is not None:
                try:
                    temporary.cleanup()
                except OSError:
                    emit("phase_failed", phase="limpieza", error_type="CleanupError")
                    response = failure(
                        identity,
                        command,
                        "limpieza",
                        "CleanupError",
                        "No se pudieron eliminar los archivos temporales",
                        500,
                    )
        # Sin logs persistentes, no recrear el directorio temporal ya eliminado.
        if logs_dir is None:
            events = None
        emit(
            "request_completed",
            status="completed" if response.status_code == 200 else "failed",
            seconds=round(time.perf_counter() - started, 6),
        )
        return response

    return app
