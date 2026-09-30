"""CLI del motor pdfsum.

Subcomandos:
  run                transcribe, revisa abstracts y genera solo como respaldo.
  transcribe         solo transcribe PDFs a ocr/<doc_id>.txt (cacheado).
  extract-abstracts  transcribe PDFs y extrae resúmenes existentes sin generarlos.
  summarize          genera un abstract textual sin buscar resúmenes existentes.
  batch              aplica la política de respaldo a un lote de textos.
  export             exporta un lote a registros LILACS (borrador).
  serve              API de consulta de solo lectura del lote.

El flujo canonico arranca desde el PDF (la fuente): usar `run`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .abstract_generation import generate_document_abstract
from .config import (
    get_config_value,
    resolve_abstract_refine_context_chars,
    validate_ocr_workers,
)
from .contract import read_result


def _resolve_backend_model(
    backend_arg: str | None, model_arg: str | None
) -> tuple[str, str]:
    """Resuelve (backend, modelo) vía la fábrica: flag > env/config > default."""
    from .adapters.summarizer_factory import resolve_backend, resolve_model

    backend = resolve_backend(backend_arg)
    model = resolve_model(backend, model_arg)
    return backend, model


def _build_summarizer(dry_run: bool, backend: str, model: str):
    from .adapters.summarizer_factory import build_summarizer

    return build_summarizer(backend, model, dry_run=dry_run)


def _task_model(args, task: str) -> tuple[str, str]:
    """El alias legado selecciona revisión en extract-abstracts y generación en los demás."""
    from .adapters.summarizer_factory import resolve_task_backend, resolve_task_model

    backend = resolve_task_backend(
        task, getattr(args, f"{task}_backend", None), args.backend
    )
    explicit = getattr(args, f"{task}_model", None)
    alias_task = "abstract" if args.cmd == "extract-abstracts" else "summary"
    if args.model and task == alias_task:
        if explicit and explicit != args.model:
            raise ValueError("--model contradice el argumento específico")
        logging.getLogger(__name__).warning(
            "--model es un alias legado de --%s-model", task
        )
        explicit = explicit or args.model
    return backend, resolve_task_model(backend, task, explicit)


def _add_generation_options(parser):
    parser.add_argument(
        "--long-strategy",
        choices=["excerpt", "blocks", "hierarchical"],
        default=get_config_value("long_strategy", "hierarchical"),
    )
    parser.add_argument(
        "--max-chars", type=int, default=get_config_value("max_chars", 42000)
    )


def cmd_summarize(args: argparse.Namespace) -> int:
    text = Path(args.text).read_text(encoding="utf-8", errors="replace")
    doc_id = args.doc_id or Path(args.text).stem
    backend, model = _task_model(args, "summary")
    from .adapters.summarizer_factory import LazyGenerator, model_diagnostics

    generator = LazyGenerator(backend, model, args.dry_run)
    result = generate_document_abstract(
        doc_id,
        text,
        generator,
        pages=args.pages,
        lang=args.lang,
        long_strategy=args.long_strategy,
        max_chars=args.max_chars,
    )
    result.meta["models"] = model_diagnostics(None, generator, "generated")
    out = result.to_json()
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    from .adapters.batch_runner import run_batch
    from .adapters.summarizer_factory import LazyGenerator, build_reviewer

    backend, model = _task_model(args, "summary")
    abstract_backend, abstract_model = _task_model(args, "abstract")
    fake = getattr(args, "fake", False) or args.dry_run
    summarizer = LazyGenerator(backend, model, fake)
    reviewer = build_reviewer(abstract_backend, abstract_model, fake)
    report = run_batch(
        in_dir=args.in_dir,
        out_dir=args.out_dir,
        summarizer=summarizer,
        max_retries=args.max_retries,
        long_strategy=args.long_strategy,
        max_chars=args.max_chars,
        reprocess=args.reprocess,
        abstract_llm=reviewer,
        abstract_refine_context_chars=args.abstract_refine_context_chars,
    )
    m = report["metrics"]
    processing_failures = report["progress"]["failed"]
    print(
        f"lote: {m['total']} docs | ok={m['ok']} fallos={m['con_fallos']} "
        f"errores_procesamiento={processing_failures} "
        f"| tipos={m['por_tipo']} idiomas={m['por_idioma']} "
        f"| tiempo_medio={m['tiempo_medio']}s"
    )
    return 1 if processing_failures else 0


def cmd_export(args: argparse.Namespace) -> int:
    import json

    from .export import to_lilacs

    base = Path(args.in_dir)
    records = []
    for f in sorted(base.glob("*.json")):
        if f.name in ("report.json", "_jobs.json"):
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        d.pop("_qa", None)
        records.append(to_lilacs(read_result(d)))
    Path(args.out).write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"export LILACS (borrador): {len(records)} registros -> {args.out}")
    return 0


def cmd_bibframe(args: argparse.Namespace) -> int:
    """Registros bibliográficos BIBFRAME (JSON-LD), uno por documento/PDF."""
    import json

    from .bibframe import has_minimum_data, merge_bib_sources, to_bibframe

    base = Path(args.in_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir = Path(args.pdfs_dir) if args.pdfs_dir else None

    generated: list[str] = []
    skipped: list[dict] = []
    for f in sorted(base.glob("*.json")):
        if f.name in ("report.json", "_jobs.json"):
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        d.pop("_qa", None)
        summary = read_result(d)

        pdf_meta = None
        if pdfs_dir is not None:
            pdf_path = pdfs_dir / f"{summary.doc_id}.pdf"
            if pdf_path.exists():
                from .adapters.pdf_metadata import read_pdf_info

                pdf_meta = read_pdf_info(str(pdf_path))

        bib = merge_bib_sources(pdf_meta, summary)
        if not has_minimum_data(bib):
            skipped.append(
                {"doc_id": summary.doc_id, "motivo": "sin título (dato mínimo)"}
            )
            continue
        record = to_bibframe(bib)
        out_file = out_dir / f"{summary.doc_id}.bibframe.json"
        out_file.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        generated.append(summary.doc_id)

    report = {"generados": len(generated), "omitidos": skipped}
    (out_dir / "bibframe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"bibframe (borrador): generados={len(generated)} "
        f"omitidos={len(skipped)} -> {out_dir}"
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .adapters.api_server import serve

    serve(args.batch_dir, host=args.host, port=args.port)
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    """Arranca el servicio HTTP (FastAPI, extra opcional)."""
    import os

    from .adapters.api_service import MAX_UPLOAD_MB_DEFAULT, create_app

    token = os.environ.get("PDFSUM_API_TOKEN", "")
    if not token.strip():
        print(
            "ERROR: PDFSUM_API_TOKEN no configurado. "
            "El servicio no arranca sin token (no hay modo abierto)."
        )
        return 2

    try:
        app = create_app(
            args.workspace,
            token=token,
            max_upload_mb=args.max_upload_mb or MAX_UPLOAD_MB_DEFAULT,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 2

    try:
        import uvicorn
    except ImportError:
        print("ERROR: falta uvicorn. Instala el extra: pip install 'pdfsum[service]'")
        return 2

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    """Worker del servicio: procesa jobs encolados en el workspace."""
    from .adapters.service_worker import main_loop
    from .adapters.summarizer_factory import LazyGenerator, build_reviewer

    backend, model = _task_model(args, "summary")
    abstract_backend, abstract_model = _task_model(args, "abstract")
    fake = getattr(args, "fake", False) or args.dry_run
    summarizer = LazyGenerator(backend, model, fake)
    reviewer = build_reviewer(abstract_backend, abstract_model, fake)
    transcriber = _build_transcriber(
        args.fake,
        args.lang,
        vlm_model=args.vlm_model,
        ocr_workers=args.ocr_workers,
        vlm_workers=args.vlm_workers,
    )

    main_loop(
        args.workspace,
        transcriber,
        summarizer,
        abstract_llm=reviewer,
        abstract_refine_context_chars=args.abstract_refine_context_chars,
        long_strategy=args.long_strategy,
        max_chars=args.max_chars,
        interval_seconds=args.interval,
        reprocess=args.reprocess,
    )
    return 0


def _build_transcriber(
    fake: bool,
    lang: str,
    vlm_model: str | None = None,
    ocr_workers: int | None = None,
    vlm_workers: int | None = None,
):
    """Transcriptor por defecto: híbrido nativo+Tesseract con fallback VLM.

    Si Ollama + el modelo de visión están disponibles, el híbrido los usa como
    fallback para escaneos de baja confianza (color/contraste); si no, degrada
    a Tesseract con aviso (la app sigue funcional).
    """
    ocr_workers = validate_ocr_workers(
        ocr_workers if ocr_workers is not None else get_config_value("ocr_workers", 2),
        "ocr_workers",
    )
    vlm_workers = validate_ocr_workers(
        vlm_workers if vlm_workers is not None else get_config_value("vlm_workers", 1),
        "vlm_workers",
    )
    if fake:
        from .adapters.fake_transcriber import FakeTranscriber

        return FakeTranscriber(text="texto de prueba " * 20, pages=1)
    from .adapters.doctor import _ollama_models
    from .adapters.hybrid_ocr import HybridOcrTranscriber

    vlm = None
    try:
        from .adapters.vlm_ocr import VlmPageOCR, resolve_vlm_model

        resolved_vlm_model = resolve_vlm_model(vlm_model)
        models = _ollama_models() or []
        if resolved_vlm_model in models:
            vlm = VlmPageOCR(model=resolved_vlm_model)
        else:
            print(
                f"aviso: modelo VLM '{resolved_vlm_model}' no disponible; "
                "OCR de escaneos de baja confianza degradará a Tesseract."
            )
    except (OSError, ValueError):
        print("aviso: Ollama no accesible; OCR de baja confianza usará Tesseract.")
    return HybridOcrTranscriber(
        lang=lang, vlm=vlm, ocr_workers=ocr_workers, vlm_workers=vlm_workers
    )


def cmd_run(args: argparse.Namespace) -> int:
    """Transcribe, revisa y genera solamente cuando no quedan abstracts válidos."""
    from .adapters.pdf_batch import run_batch_pdfs
    from .adapters.summarizer_factory import LazyGenerator, build_reviewer
    from .workspace import Workspace

    backend, model = _task_model(args, "summary")
    abstract_backend, abstract_model = _task_model(args, "abstract")
    fake = getattr(args, "fake", False) or args.dry_run
    summarizer = LazyGenerator(backend, model, fake)
    reviewer = build_reviewer(abstract_backend, abstract_model, fake)
    ws = Workspace(args.workspace, logs_dir=args.logs_dir)
    transcriber = _build_transcriber(
        args.fake,
        args.lang,
        vlm_model=args.vlm_model,
        ocr_workers=args.ocr_workers,
        vlm_workers=args.vlm_workers,
    )
    report = run_batch_pdfs(
        args.in_dir,
        ws,
        transcriber,
        summarizer,
        abstract_llm=reviewer,
        abstract_refine_context_chars=args.abstract_refine_context_chars,
        long_strategy=args.long_strategy,
        max_chars=args.max_chars,
        retranscribe=args.retranscribe,
    )
    m = report["metrics"]
    processing_failures = report["progress"]["failed"]
    print(
        f"run: {m['total']} PDFs | ok={m['ok']} fallos={m['con_fallos']} "
        f"errores_procesamiento={processing_failures} "
        f"| tipos={m['por_tipo']} | ocr={ws.ocr_dir} "
        f"| resumenes={ws.summaries_dir}"
    )
    return 1 if processing_failures else 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Solo transcribe los PDFs a ocr/<doc_id>.txt (sin resumir)."""
    from .adapters.pdf_batch import transcribe_pdfs
    from .workspace import Workspace

    ws = Workspace(args.workspace)
    transcriber = _build_transcriber(
        args.fake,
        args.lang,
        vlm_model=args.vlm_model,
        ocr_workers=args.ocr_workers,
        vlm_workers=args.vlm_workers,
    )
    meta = transcribe_pdfs(args.in_dir, ws, transcriber, retranscribe=args.retranscribe)
    cached = sum(1 for m in meta.values() if m.get("cached"))
    print(f"transcribe: {len(meta)} PDFs ({cached} cacheados) -> {ws.ocr_dir}")
    return 0


def cmd_extract_abstracts(args: argparse.Namespace) -> int:
    """Transcribe PDFs y extrae solamente los resúmenes presentes."""
    from .adapters.abstract_batch import extract_abstracts_from_pdfs
    from .adapters.summarizer_factory import build_reviewer
    from .workspace import Workspace

    backend, model = _task_model(args, "abstract")
    llm = build_reviewer(backend, model, args.fake or args.dry_run)
    ws = Workspace(args.workspace, logs_dir=args.logs_dir)
    transcriber = _build_transcriber(
        args.fake,
        args.lang,
        vlm_model=args.vlm_model,
        ocr_workers=args.ocr_workers,
        vlm_workers=args.vlm_workers,
    )
    report = extract_abstracts_from_pdfs(
        args.in_dir,
        ws,
        transcriber,
        llm,
        args.abstract_refine_context_chars,
        abstract_refine_debug_dir=args.abstract_refine_debug_dir,
        backend="fake" if args.fake or args.dry_run else backend,
        model=None if args.fake or args.dry_run else model,
    )
    print(
        f"revisión_llm_exitosa={report['metrics']['revision_llm_exitosa']} "
        f"fallback_determinista={report['metrics']['fallback_determinista']} | "
        f"extract-abstracts: {report['total']} PDFs | encontrados={report['found']} sin_resumen={report['not_found']} | salida={ws.abstracts_dir}"
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Verifica dependencias de sistema y modelos."""
    from .adapters.doctor import (
        capabilities,
        check_environment,
        check_task_models,
        environment_ok,
        format_capabilities,
        format_report,
    )
    from .adapters.vlm_ocr import resolve_vlm_model

    backend, model = _task_model(args, "summary")
    abstract_backend, abstract_model = _task_model(args, "abstract")
    vlm_model = resolve_vlm_model(args.vlm_model)
    checks = check_environment(text_model=model, backend=backend, vlm_model=vlm_model)
    checks.extend(
        check_task_models(
            backend, abstract_model, model, vlm_model, abstract_backend=abstract_backend
        )
    )
    print(f"Verificación de entorno pdfsum (backend textual: {backend}):")
    print(format_report(checks))
    print("\nCapacidades disponibles:")
    caps = capabilities(checks)
    print(format_capabilities(caps))
    ok = environment_ok(checks)
    print(f"\nExtraer PDFs nativos: {'OK' if ok else 'INCOMPLETO'}")
    if not caps["resumen"]:
        print(
            "AVISO: sin backend de resumen listo (Ollama+modelo, o API key "
            "cloud) no se pueden generar abstracts de respaldo. La extracción "
            "determinista sigue disponible. Ver INSTALL.md §2."
        )
    return 0 if ok else 1


def _preflight_resumen(model: str, backend: str = "ollama") -> int | None:
    """Comprueba precondiciones de resumen; devuelve código de error o None."""
    from .adapters.doctor import summarization_ready

    ok, msg = summarization_ready(model, backend=backend)
    if not ok:
        print("Precondición no cumplida para resumir:\n" + msg)
        return 2
    return None


def _find_samples_dir() -> Path:
    """Localiza el directorio samples en el repo o entorno de ejecución."""
    candidates = [
        Path.cwd() / "samples",
        Path(__file__).resolve().parents[2] / "samples",
    ]

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    raise FileNotFoundError(
        "No se encontró el directorio 'samples'. "
        "Ejecuta desde la raíz del proyecto o indica "
        "--pdfs y --control explícitamente."
    )


def cmd_verify(args: argparse.Namespace) -> int:
    """Corre el flujo sobre la muestra incluida y evalúa contra el control set."""
    from .acceptance import acceptance_verdict, load_control_set
    from .adapters.pdf_batch import run_batch_pdfs
    from .contract import read_result
    from .control import run_control_suite
    from .workspace import Workspace

    samples_dir = _find_samples_dir()
    pdfs = args.pdfs or str(samples_dir / "pdfs")
    control = args.control or str(samples_dir / "control_set.json")
    ws = Workspace(args.workspace)
    transcriber = _build_transcriber(
        args.fake,
        args.lang,
        vlm_model=args.vlm_model,
        ocr_workers=args.ocr_workers,
        vlm_workers=args.vlm_workers,
    )
    from .adapters.summarizer_factory import LazyGenerator, build_reviewer

    backend, model = _task_model(args, "summary")
    abstract_backend, abstract_model = _task_model(args, "abstract")
    fake = getattr(args, "fake", False) or args.dry_run
    summarizer = LazyGenerator(backend, model, fake)
    reviewer = build_reviewer(abstract_backend, abstract_model, fake)
    run_batch_pdfs(
        pdfs,
        ws,
        transcriber,
        summarizer,
        abstract_llm=reviewer,
        abstract_refine_context_chars=args.abstract_refine_context_chars,
        long_strategy=args.long_strategy,
        max_chars=args.max_chars,
    )
    # cargar resultados y evaluar contra el set de control
    results = {}
    for f in ws.summaries_dir.glob("*.json"):
        if f.name == "report.json":
            continue
        import json

        d = json.loads(f.read_text(encoding="utf-8"))
        d.pop("_qa", None)
        results[d["doc_id"]] = read_result(d)
    cases = load_control_set(control)
    rep = run_control_suite(results, cases).to_dict()
    verdict = acceptance_verdict(rep, min_coverage=args.min_coverage)
    print(f"Aceptación: {'PASS' if verdict.passed else 'FAIL'}")
    print(f"  {verdict.detail}")
    for v in rep["verdicts"]:
        if "error" in v:
            print(f"  - {v['doc_id']}: {v['error']}")
        else:
            print(
                f"  - {v['doc_id']}: cobertura {v['coverage']} "
                f"lang={'ok' if v['lang_ok'] else 'X'} "
                f"tipo={'ok' if v['type_ok'] else 'X'}"
                + (f" faltan {v['missing_terms']}" if v["missing_terms"] else "")
            )
    return 0 if verdict.passed else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdfsum",
        description=__doc__,
        epilog=(
            "Ejemplo típico (flujo completo desde PDFs):\n"
            "  pdfsum run --in ./mis_pdfs --workspace ./data --lang por\n\n"
            "Guía rápida con ejemplos ejecutables: GUIA-USO.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def _add_backend_model(sp: argparse.ArgumentParser, add_vlm=False) -> None:
        """--backend/--model comunes: resueltos por summarizer_factory (flag >
        env PDFSUM_SUMMARIZER_BACKEND / config > default 'ollama')"""
        from .adapters.summarizer_factory import BACKENDS

        sp.add_argument(
            "--backend",
            choices=BACKENDS,
            default=None,
            help="backend del resumidor (def: env PDFSUM_SUMMARIZER_BACKEND "
            "o .pdfsum-config.json, si no 'ollama')",
        )
        sp.add_argument(
            "--model",
            default=None,
            help="alias legado: --abstract-model en extract-abstracts; --summary-model en los demás",
        )
        for task in ("abstract", "summary"):
            sp.add_argument(
                f"--{task}-backend",
                choices=BACKENDS,
                default=None,
                help="backend por responsabilidad",
            )
            sp.add_argument(
                f"--{task}-model", default=None, help="modelo por responsabilidad"
            )
        if add_vlm:
            sp.add_argument(
                "--vlm-model",
                dest="vlm_model",
                default=None,
                help="modelo vlm a usar (def: config 'vlm_model', si no "
                "el default del backend)",
            )

    s = sub.add_parser("summarize", help="resumir un texto ya transcrito")
    s.add_argument("--text", required=True, help="ruta a .txt (transcripción)")
    s.add_argument("--doc-id", dest="doc_id", default=None)
    s.add_argument("--lang", default=None, help="forzar idioma (pt/es/en/...)")
    s.add_argument("--pages", type=int, default=1)
    _add_backend_model(s)
    s.add_argument(
        "--dry-run", action="store_true", help="usar resumidor fake (sin modelo)"
    )
    s.add_argument("--out", default=None, help="escribir JSON a archivo")
    _add_generation_options(s)
    s.set_defaults(func=cmd_summarize)

    b = sub.add_parser("batch", help="procesar un lote de .txt (cola + QA)")
    b.add_argument("--in", dest="in_dir", required=True, help="directorio con .txt")
    b.add_argument("--out", dest="out_dir", required=True, help="directorio salida")
    _add_backend_model(b)
    b.add_argument("--max-retries", dest="max_retries", type=int, default=2)
    b.add_argument(
        "--dry-run", action="store_true", help="usar resumidor fake (sin modelo)"
    )
    _add_generation_options(b)
    b.add_argument(
        "--reprocess",
        action="store_true",
        help="reprocesar jobs explícitamente sin borrar OCR",
    )
    b.set_defaults(func=cmd_batch)

    e = sub.add_parser("export", help="exportar lote a registros LILACS (borrador)")
    e.add_argument("--in", dest="in_dir", required=True, help="dir del lote")
    e.add_argument("--out", required=True, help="archivo .json de salida")
    e.set_defaults(func=cmd_export)

    bf = sub.add_parser(
        "bibframe",
        help="registros bibliográficos BIBFRAME JSON-LD, uno por documento",
    )
    bf.add_argument(
        "--in", dest="in_dir", required=True, help="dir de summaries del lote"
    )
    bf.add_argument(
        "--pdfs",
        dest="pdfs_dir",
        default=None,
        help="dir con los PDFs originales (opcional: añade metadata embebida "
        "del PDF con precedencia sobre el resumen)",
    )
    bf.add_argument(
        "--out", required=True, help="dir de salida (<doc_id>.bibframe.json)"
    )
    bf.set_defaults(func=cmd_bibframe)

    sv = sub.add_parser("serve", help="API de consulta de solo lectura del lote")
    sv.add_argument("--batch-dir", dest="batch_dir", required=True)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(func=cmd_serve)

    api = sub.add_parser(
        "api",
        help="servicio HTTP (FastAPI, extra opcional) para subir PDFs y encolar jobs",
    )
    api.add_argument(
        "--workspace",
        required=True,
        help="workspace del servicio (inbox/, ocr/, summaries/, service_jobs/)",
    )
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8766)
    api.add_argument(
        "--max-upload-mb",
        dest="max_upload_mb",
        type=int,
        default=None,
        help="límite de tamaño por upload (def: 100MB)",
    )
    api.set_defaults(func=cmd_api)

    w = sub.add_parser("worker", help="worker del servicio (consume la cola)")
    w.add_argument(
        "--workspace",
        required=True,
        help="workspace del servicio (mismo que el API)",
    )
    w.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="segundos entre polls de la cola (def 1.0)",
    )
    w.add_argument(
        "--lang",
        default=get_config_value("lang", "por+eng+spa"),
        help="idioma(s) OCR Tesseract (def: por+eng+spa)",
    )
    _add_backend_model(w, add_vlm=True)
    w.add_argument(
        "--long-strategy",
        dest="long_strategy",
        default=get_config_value("long_strategy", "hierarchical"),
        choices=["excerpt", "blocks", "hierarchical"],
    )
    w.add_argument("--dry-run", action="store_true", help="resumidor fake")
    w.add_argument("--fake", action="store_true", help="transcriber + resumidor fake")
    w.add_argument(
        "--reprocess",
        action="store_true",
        help="reprocesar una vez los jobs terminados sin borrar OCR",
    )
    w.set_defaults(func=cmd_worker)

    r = sub.add_parser("run", help="flujo completo desde PDFs (transcribe+resume)")
    r.add_argument("--in", dest="in_dir", required=True, help="directorio de PDFs")
    r.add_argument(
        "--workspace", required=True, help="dir de artefactos (ocr/, summaries/)"
    )
    r.add_argument(
        "--logs-dir",
        default=None,
        help=("directorio para report.json (por defecto: <workspace>/summaries)"),
    )
    r.add_argument(
        "--lang",
        default=get_config_value("lang", "por+eng+spa"),
        help="idioma(s) OCR Tesseract, combinables con '+' "
        "(default: por+eng+spa; ej. anadir frances: "
        "por+eng+spa+fra)",
    )
    _add_backend_model(r, add_vlm=True)
    r.add_argument(
        "--long-strategy",
        dest="long_strategy",
        default=get_config_value("long_strategy", "hierarchical"),
        choices=["excerpt", "blocks", "hierarchical"],
    )
    r.add_argument(
        "--retranscribe",
        action="store_true",
        help="forzar re-OCR aun con caché válida (regenera ocr/*.meta.json)",
    )
    r.add_argument("--dry-run", action="store_true", help="resumidor fake (OCR real)")
    r.add_argument(
        "--fake",
        action="store_true",
        help="transcriber Y resumidor fake (sin poppler/ollama)",
    )
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("transcribe", help="solo transcribir PDFs a ocr/*.txt")
    t.add_argument("--in", dest="in_dir", required=True, help="directorio de PDFs")
    t.add_argument("--workspace", required=True)
    t.add_argument("--lang", default="por+eng+spa")
    t.add_argument(
        "--vlm-model",
        dest="vlm_model",
        default=None,
        help="modelo vlm a usar (def: config 'vlm_model', si no "
        "el default del backend)",
    )
    t.add_argument(
        "--retranscribe",
        action="store_true",
        help="forzar re-OCR aun con caché válida (regenera ocr/*.meta.json)",
    )
    t.add_argument("--fake", action="store_true")
    t.set_defaults(func=cmd_transcribe)

    a = sub.add_parser(
        "extract-abstracts",
        help="transcribir PDFs y extraer solamente resúmenes presentes",
    )
    a.add_argument("--in", dest="in_dir", required=True, help="directorio de PDFs")
    a.add_argument("--workspace", required=True, help="directorio de artefactos")
    a.add_argument("--logs-dir", default=None, help="directorio opcional para reportes")
    a.add_argument(
        "--lang",
        default=get_config_value("lang", "por+eng+spa"),
        help=("idioma(s) OCR Tesseract, combinables con '+' (default: por+eng+spa)"),
    )
    a.add_argument(
        "--fake", action="store_true", help="usar transcriptor y LLM fake para pruebas"
    )
    _add_backend_model(a, add_vlm=True)
    a.add_argument("--dry-run", action="store_true", help="usar LLM fake (OCR real)")
    a.add_argument(
        "--abstract-refine-debug-dir",
        default=None,
        help="guardar respuestas crudas de revisión para diagnóstico (datos sensibles)",
    )
    a.set_defaults(func=cmd_extract_abstracts)

    d = sub.add_parser("doctor", help="verificar dependencias de sistema/modelos")
    _add_backend_model(d, add_vlm=True)
    d.set_defaults(func=cmd_doctor)

    v = sub.add_parser("verify", help="verificar resultados sobre la muestra incluida")
    v.add_argument(
        "--workspace", default="./_verify", help="dir de artefactos de la verificación"
    )
    v.add_argument("--pdfs", default=None, help="dir de PDFs (def: muestra)")
    v.add_argument("--control", default=None, help="set de control (def: incluido)")
    v.add_argument("--lang", default="por+eng+spa")
    _add_backend_model(v, add_vlm=True)
    v.add_argument(
        "--long-strategy",
        dest="long_strategy",
        default=get_config_value("long_strategy", "hierarchical"),
        choices=["excerpt", "blocks", "hierarchical"],
    )
    v.add_argument("--min-coverage", dest="min_coverage", type=float, default=0.6)
    v.add_argument("--dry-run", action="store_true")
    v.add_argument(
        "--fake",
        action="store_true",
        help="transcriber+resumidor fake (prueba el arnés)",
    )
    v.set_defaults(func=cmd_verify)
    for command in (r, w, v):
        command.add_argument(
            "--max-chars", type=int, default=get_config_value("max_chars", 42000)
        )
    for command in (r, t, a, w, v):
        command.add_argument(
            "--ocr-workers",
            type=int,
            default=None,
            help="páginas OCR simultáneas (def: config ocr_workers, si no 2; 1 secuencial)",
        )
        command.add_argument(
            "--vlm-workers",
            type=int,
            default=None,
            help="llamadas VLM simultáneas por transcriptor (def: config vlm_workers, si no 1)",
        )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.func in (
        cmd_extract_abstracts,
        cmd_run,
        cmd_batch,
        cmd_verify,
        cmd_worker,
    ):
        try:
            args.abstract_refine_context_chars = resolve_abstract_refine_context_chars()
        except ValueError as exc:
            print(str(exc))
            return 2
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"Configuración o resultado inválido: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"No se pudo completar el procesamiento: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
