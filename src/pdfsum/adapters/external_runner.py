"""Orquestación externa independiente del proveedor de entradas y resultados."""

from __future__ import annotations

import hashlib
import sys
from uuid import uuid4

from ..external import (
    INPUT_TYPES,
    Command,
    ExternalResult,
    InputMaterializer,
    InputProcessor,
    InputSource,
    ResultStore,
)
from ..workspace import Workspace
from .observability import EventLog


class ResultStoreError(RuntimeError):
    """Conserva el envelope y el ID original si la persistencia falla."""

    def __init__(self, result: ExternalResult, reference: str, error_type: str):
        super().__init__(
            f"No se pudo persistir el resultado; referencia={reference}; "
            f"comando={result.command}; fase=persistencia; tipo={error_type}"
        )
        self.result = result
        self.id = result.id
        self.phase = "persistencia"
        self.error_type = error_type


class ArtifactCleanupError(RuntimeError):
    """Fallo de limpieza con identidad original y referencia segura del intento."""

    def __init__(self, identifier: object, reference: str):
        super().__init__(f"No se pudieron limpiar artefactos; referencia={reference}")
        self.id = identifier
        self.phase = "limpieza"


def execute_external(
    command: Command,
    source: InputSource,
    materializer: InputMaterializer,
    processor: InputProcessor,
    store: ResultStore,
    workspace: Workspace,
    *,
    keep_artifacts: bool = False,
) -> dict[str, int]:
    """Procesa secuencialmente; los errores recuperables se guardan con su ID.

    La fuente y el store son responsables de reservas, confirmación y reintentos.
    No acumula transcripciones ni resultados completos del lote en memoria.
    """
    if command not in INPUT_TYPES:
        raise ValueError("Comando externo no admitido")
    workspace.downloads_dir.mkdir(parents=True, exist_ok=True)
    events = EventLog(workspace.report_path.parent / "events.jsonl", uuid4().hex)
    totals = {"completed": 0, "failed": 0}
    for entry in source.pending(command):
        # Solo la referencia local se serializa; el ID opaco no se transforma.
        reference = (
            hashlib.sha256(
                (type(entry.id).__name__ + repr(entry.id)).encode("utf-8")
            ).hexdigest()[:20]
            + "-"
            + uuid4().hex
        )
        suffix = ".pdf" if INPUT_TYPES[command] == "pdf" else ".txt"
        path = workspace.downloads_dir / (reference + suffix)
        phase = "validacion"
        cleanup = []
        processing_started = False
        materialization_started = False

        def emit(event: str, *, reference=reference, **fields) -> None:
            events.write(
                event,
                external_id_reference=reference,
                command=command,
                phase=phase,  # noqa: B023 — uso síncrono
                **fields,
            )

        try:
            try:
                emit("external_started")
                if entry.input_type != INPUT_TYPES[command]:
                    raise ValueError("Tipo de entrada incompatible con el comando")
                cleanup = list(processor.temporary_results(command, path))
                for artifact in cleanup:
                    if (
                        artifact.parent
                        not in {workspace.summaries_dir, workspace.abstracts_dir}
                        or artifact.name != reference + ".json"
                        or artifact.exists()
                        or artifact.is_symlink()
                    ):
                        cleanup = []
                        raise ValueError(
                            "Ruta de resultado no exclusiva o no permitida"
                        )
                phase = "materializacion"
                if path.exists() or path.is_symlink():
                    raise ValueError("La ruta de descarga ya existe")
                materialization_started = True
                materializer.materialize(entry, path)
                phase = "procesamiento"
                processing_started = True
                payload = processor.process(command, path)
                result = ExternalResult(entry.id, command, "completed", result=payload)
            except Exception as exc:  # noqa: BLE001 — aislar errores de adapters
                result = ExternalResult(
                    entry.id,
                    command,
                    "failed",
                    phase=phase,
                    error_type=type(exc).__name__,
                    error=f"Falló la fase de {phase}; detalle omitido por privacidad",
                )
            phase = "persistencia"
            try:
                store.save(result)
            except Exception as exc:  # noqa: BLE001 — aislar errores de adapters
                emit(
                    "external_store_failed",
                    error_type=type(exc).__name__,
                    error="No se pudo persistir el resultado",
                )
                raise ResultStoreError(result, reference, type(exc).__name__) from None
            totals[result.status] += 1
            emit(
                "external_completed",
                status=result.status,
                failure_phase=result.phase,
                error_type=result.error_type,
                error=result.error,
            )
        finally:
            if not keep_artifacts:
                # Nunca se borra un árbol ni se incluyen OCR o logs en la lista.
                interrupted = sys.exc_info()[0] is not None
                artifacts = ([path] if materialization_started else []) + (
                    cleanup if processing_started else []
                )
                cleanup_failed = False
                for artifact in artifacts:
                    try:
                        artifact.unlink(missing_ok=True)
                    except OSError:
                        cleanup_failed = True
                if cleanup_failed:
                    phase = "limpieza"
                    emit(
                        "external_cleanup_failed",
                        error="No se pudieron limpiar artefactos",
                    )
                    if not interrupted:
                        raise ArtifactCleanupError(entry.id, reference) from None
    return totals
