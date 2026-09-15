"""API síncrona de extracción; la identidad externa nunca determina rutas."""

import json
import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..workspace import Workspace
from .abstract_batch import extract_abstracts_from_pdfs
from .observability import EventLog
from .pdf_download import PDFDownloader, validate_pdf_url


def process_pdf(pdf: Path, workspace: Workspace, transcriber, llm, **options) -> dict:
    """Ejecuta el mismo pipeline del CLI y lee su JSON principal sin transformarlo."""
    extract_abstracts_from_pdfs(
        str(pdf.parent),
        workspace,
        transcriber,
        llm,
        format_error=lambda exc: "Fallo del procesamiento; detalle omitido",
        **options,
    )
    return json.loads(workspace.abstract_path(pdf.stem).read_text(encoding="utf-8"))


def create_app(
    workspace: str | Path,
    *,
    processor: Callable[[Path, Workspace], dict],
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
    app = FastAPI(title="Extracción de resúmenes existentes")

    def failure(identity, phase, error_type, message, code):
        return JSONResponse(
            status_code=code,
            content={
                "id": identity,
                "status": "failed",
                "phase": phase,
                "error_type": error_type,
                "error": message,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_json(request, exc):
        identity = exc.body.get("id") if isinstance(exc.body, dict) else None
        return failure(identity, "validation", "ValidationError", "JSON inválido", 422)

    @app.post("/api/extract-abstracts")
    def extract(body: Any = Body(default=None)):  # noqa: B008 — declaración de FastAPI
        identity = body.get("id") if isinstance(body, dict) else None
        valid_id = (type(identity) is int and identity > 0) or (
            isinstance(identity, str)
            and 0 < len(identity) <= 256
            and bool(identity.strip())
            and not any(ord(c) < 32 or ord(c) == 127 for c in identity)
        )
        if not valid_id:
            return failure(
                identity,
                "validation",
                "ValidationError",
                "id debe ser un entero positivo o texto no vacío de hasta 256 caracteres",
                422,
            )
        if set(body) != {"id", "url"}:
            return failure(
                identity,
                "validation",
                "ValidationError",
                "La solicitud debe contener solamente id y url",
                422,
            )
        try:
            validate_pdf_url(body["url"])
        except (ValueError, TypeError):
            return failure(
                identity,
                "validation",
                "ValidationError",
                "URL HTTP inválida o destino no permitido",
                422,
            )

        run_id = uuid4().hex
        started = time.perf_counter()
        phase = "processing"
        temporary = None
        events = None

        def emit(event, **fields):
            logger.info("Extracción HTTP: %s (%s)", event, run_id, extra=fields)
            if events is not None:
                try:
                    events.write(event, **fields)
                except OSError:
                    logger.warning("No se pudo escribir el evento HTTP (%s)", run_id)

        try:
            temporary = tempfile.TemporaryDirectory(
                prefix=f"abstract-{run_id}-", dir=root
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
            phase = "download"
            emit("phase_started", phase=phase)
            downloader.download(body["url"], pdf)
            phase = "processing"
            emit("phase_started", phase=phase)
            result = processor(pdf, ws)
            response = JSONResponse(
                {"id": identity, "status": "completed", "result": result}
            )
        except Exception:  # noqa: BLE001 — frontera HTTP sin detalles internos
            error_type = "DownloadError" if phase == "download" else "ProcessingError"
            emit("phase_failed", phase=phase, error_type=error_type)
            response = failure(
                identity,
                phase,
                error_type,
                "No se pudo descargar el PDF"
                if phase == "download"
                else "No se pudo procesar el PDF",
                502 if phase == "download" else 500,
            )
        finally:
            if temporary is not None:
                try:
                    temporary.cleanup()
                except OSError:
                    emit("phase_failed", phase="cleanup", error_type="CleanupError")
                    response = failure(
                        identity,
                        "cleanup",
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
