"""API de procesamiento asíncrona (adaptador de entrada, FASE20).

Sube PDFs por HTTP y encola jobs que el proceso `pdfsum worker` ejecuta
con el pipeline existente. El dominio no cambia: esta capa solo traduce
HTTP <-> puertos (JobStore/Workspace). FastAPI es dependencia OPCIONAL
(`pip install pdfsum[service]`); el core y la CLI no la requieren.

Seguridad: token Bearer obligatorio (sin token no hay servicio), límite
de tamaño de upload, validación por magic bytes (%PDF-), doc_id derivado
del hash (los nombres del cliente jamás forman rutas).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .. import __version__
from ..queue import DONE, PENDING, Job, job_key
from ..workspace import Workspace
from .job_store import DirJobStore
from .ocr_meta import OCR_PIPELINE_VERSION

MAX_UPLOAD_MB_DEFAULT = 100
_PDF_MAGIC = b"%PDF-"
_STEM_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _require_fastapi():
    try:
        import fastapi  # noqa: F401
    except ImportError as exc:  # pragma: no cover - mensaje de instalación
        raise RuntimeError(
            "El modo servicio requiere el extra opcional: "
            "pip install 'pdfsum[service]' (fastapi + uvicorn + "
            "python-multipart)."
        ) from exc


def sanitize_stem(filename: str) -> str:
    """Resto del doc_id: SOLO caracteres seguros del nombre del cliente."""
    stem = Path(filename or "doc").stem
    clean = _STEM_SAFE.sub("_", stem).strip("_")[:40]
    return clean or "doc"


def make_doc_id(data: bytes, filename: str) -> tuple[str, str, str]:
    """(doc_id, sha256, display_name): identidad por CONTENIDO.

    FASE20: idempotencia exige que doc_id no dependa del nombre del fichero.
    """
    sha = hashlib.sha256(data).hexdigest()
    return sha[:12], sha, sanitize_stem(filename)


def service_paths(workspace_root: str | Path) -> dict[str, Path]:
    root = Path(workspace_root)
    return {
        "inbox": root / "inbox",
        "jobs_store": root / "service_jobs",
        "jobs_logs": root / "jobs",
    }


def create_app(
    workspace_root: str | Path,
    token: str,
    max_upload_mb: int = MAX_UPLOAD_MB_DEFAULT,
):
    """Construye la app FastAPI del servicio. `token` es OBLIGATORIO."""
    _require_fastapi()
    from fastapi import Depends, FastAPI, File, Header, HTTPException

    if not (token or "").strip():
        raise ValueError(
            "PDFSUM_API_TOKEN vacío: el servicio no arranca sin token "
            "(no existe modo abierto)."
        )

    ws = Workspace(workspace_root)
    paths = service_paths(workspace_root)
    store = DirJobStore(paths["jobs_store"])
    max_bytes = max_upload_mb * 1024 * 1024

    def auth(authorization: str | None = Header(None)) -> None:
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="token inválido")

    app = FastAPI(
        title="pdfsum service",
        version=__version__,
        dependencies=[Depends(auth)],
    )

    def _job_response(job: dict) -> dict:
        out = {
            "job_id": job["key"],
            "doc_id": job["doc_id"],
            "status": job["state"],
            "attempts": job.get("attempts", 0),
        }
        if job.get("error"):
            out["error"] = job["error"]
        if job["state"] == DONE:
            out["summary_url"] = f"/api/summaries/{job['doc_id']}"
        return out

    @app.post("/api/documents", status_code=202)
    async def upload(file=File(...)) -> dict:  # noqa: B008
        data = await file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail="PDF demasiado grande")
        if not data.startswith(_PDF_MAGIC):
            raise HTTPException(status_code=415, detail="el contenido no es un PDF")
        doc_id, sha, display = make_doc_id(data, file.filename or "doc")
        key = job_key(doc_id, sha)
        existing = store.get(key)
        if existing:
            return _job_response(existing)
        if ws.summary_path(doc_id).exists():
            job = Job(key=key, doc_id=doc_id, state=DONE)
            d = job.to_dict()
            store.put(key, d)
            return _job_response(d)
        # inbox/<doc_id>/<doc_id>.pdf: un dir por doc para el worker
        doc_dir = paths["inbox"] / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / f"{doc_id}.pdf").write_bytes(data)
        (doc_dir / "upload_name.txt").write_text(display + "\n", encoding="utf-8")
        job = Job(key=key, doc_id=doc_id, state=PENDING)
        d = job.to_dict()
        store.put(key, d)
        return _job_response(d)

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job desconocido")
        return _job_response(job)

    @app.get("/api/summaries")
    def summaries() -> list[dict]:
        out = []
        if ws.summaries_dir.exists():
            for f in sorted(ws.summaries_dir.glob("*.json")):
                if f.name == "report.json":
                    continue
                d = json.loads(f.read_text(encoding="utf-8"))
                qa = d.get("_qa", {})
                out.append(
                    {
                        "doc_id": d.get("doc_id"),
                        "tipo": d.get("tipo_documento"),
                        "idioma": d.get("idioma_principal"),
                        "qa_ok": qa.get("passed"),
                        "transcript_ok": qa.get("transcript", {}).get("passed"),
                    }
                )
        return out

    @app.get("/api/summaries/{doc_id}")
    def summary(doc_id: str) -> dict:
        try:
            f = ws.summary_path(doc_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not f.exists():
            raise HTTPException(status_code=404, detail="doc desconocido")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.get("/api/report")
    def report() -> dict:
        f = ws.report_path
        if not f.exists():
            raise HTTPException(status_code=404, detail="sin report")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health() -> dict:
        states: dict[str, int] = {}
        for job in store.all().values():
            states[job["state"]] = states.get(job["state"], 0) + 1
        return {
            "status": "ok",
            "version": __version__,
            "ocr_pipeline_version": OCR_PIPELINE_VERSION,
            "queue": states,
        }

    return app
