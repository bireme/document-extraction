"""CLI del motor pdfsum.

Subcomandos:
  run         flujo completo desde PDFs: transcribe (OCR) -> resume -> report.
  transcribe  solo transcribe PDFs a ocr/<doc_id>.txt (cacheado).
  summarize   resume un texto ya transcrito (paso 2 aislado).
  batch       resume un lote de .txt (cola idempotente + QA gates).
  export      exporta un lote a registros LILACS (borrador).
  serve       API de consulta de solo lectura del lote.

El flujo canonico arranca desde el PDF (la fuente): usar `run`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import get_config_value
from .contract import SummaryResult
from .pipeline import summarize_document


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


def cmd_summarize(args: argparse.Namespace) -> int:
    text = Path(args.text).read_text(encoding="utf-8", errors="replace")
    doc_id = args.doc_id or Path(args.text).stem
    backend, model = _resolve_backend_model(args.backend, args.model)
    summarizer = _build_summarizer(args.dry_run, backend, model)
    result = summarize_document(
        doc_id=doc_id,
        text=text,
        summarizer=summarizer,
        pages=args.pages,
        lang=args.lang,
    )
    out = result.to_json()
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    from .adapters.batch_runner import run_batch

    backend, model = _resolve_backend_model(args.backend, args.model)
    if not args.dry_run:
        err = _preflight_resumen(model, backend)
        if err is not None:
            return err
    summarizer = _build_summarizer(args.dry_run, backend, model)
    report = run_batch(
        in_dir=args.in_dir,
        out_dir=args.out_dir,
        summarizer=summarizer,
        max_retries=args.max_retries,
    )
    m = report["metrics"]
    print(
        f"lote: {m['total']} docs | ok={m['ok']} fallos={m['con_fallos']} "
        f"| tipos={m['por_tipo']} idiomas={m['por_idioma']} "
        f"| tiempo_medio={m['tiempo_medio']}s"
    )
    return 0


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
        records.append(to_lilacs(SummaryResult.from_dict(d)))
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
        summary = SummaryResult.from_dict(d)

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


def _build_transcriber(fake: bool, lang: str, vlm_model: str = "qwen3-vl:8b-instruct"):
    """Transcriptor por defecto: híbrido nativo+Tesseract con fallback VLM.

    Si Ollama + el modelo de visión están disponibles, el híbrido los usa como
    fallback para escaneos de baja confianza (color/contraste); si no, degrada
    a Tesseract con aviso (la app sigue funcional).
    """
    if fake:
        from .adapters.fake_transcriber import FakeTranscriber

        return FakeTranscriber(text="texto de prueba " * 20, pages=1)
    from .adapters.doctor import _ollama_models
    from .adapters.hybrid_ocr import HybridOcrTranscriber

    vlm = None
    try:
        models = _ollama_models() or []
        base = vlm_model.split(":")[0]
        if any(m.startswith(base) for m in models):
            from .adapters.vlm_ocr import VlmPageOCR

            vlm = VlmPageOCR(model=vlm_model)
        else:
            print(
                f"aviso: modelo VLM '{vlm_model}' no disponible; "
                "OCR de escaneos de baja confianza degradará a Tesseract."
            )
    except (OSError, ValueError):
        print("aviso: Ollama no accesible; OCR de baja confianza usará Tesseract.")
    return HybridOcrTranscriber(lang=lang, vlm=vlm)


def cmd_run(args: argparse.Namespace) -> int:
    """Flujo completo desde PDFs: transcribe (cache) -> resume -> report."""
    from .adapters.pdf_batch import run_batch_pdfs
    from .workspace import Workspace

    backend, model = _resolve_backend_model(args.backend, args.model)
    if not (args.fake or args.dry_run):
        err = _preflight_resumen(model, backend)
        if err is not None:
            return err
    ws = Workspace(args.workspace)
    transcriber = _build_transcriber(args.fake, args.lang)
    summarizer = _build_summarizer(args.fake or args.dry_run, backend, model)
    report = run_batch_pdfs(
        args.in_dir,
        ws,
        transcriber,
        summarizer,
        long_strategy=args.long_strategy,
    )
    m = report["metrics"]
    print(
        f"run: {m['total']} PDFs | ok={m['ok']} fallos={m['con_fallos']} "
        f"| tipos={m['por_tipo']} | ocr={ws.ocr_dir} "
        f"| resumenes={ws.summaries_dir}"
    )
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Solo transcribe los PDFs a ocr/<doc_id>.txt (sin resumir)."""
    from .adapters.pdf_batch import transcribe_pdfs
    from .workspace import Workspace

    ws = Workspace(args.workspace)
    transcriber = _build_transcriber(args.fake, args.lang)
    meta = transcribe_pdfs(args.in_dir, ws, transcriber)
    cached = sum(1 for m in meta.values() if m.get("cached"))
    print(f"transcribe: {len(meta)} PDFs ({cached} cacheados) -> {ws.ocr_dir}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Verifica dependencias de sistema y modelos."""
    from .adapters.doctor import (
        capabilities,
        check_environment,
        environment_ok,
        format_capabilities,
        format_report,
    )

    backend, model = _resolve_backend_model(args.backend, args.model)
    checks = check_environment(text_model=model, backend=backend)
    print(f"Verificación de entorno pdfsum (backend de resumen: {backend}):")
    print(format_report(checks))
    print("\nCapacidades disponibles:")
    caps = capabilities(checks)
    print(format_capabilities(caps))
    ok = environment_ok(checks)
    print(f"\nExtraer PDFs nativos: {'OK' if ok else 'INCOMPLETO'}")
    if not caps["resumen"]:
        print(
            "AVISO: sin backend de resumen listo (Ollama+modelo, o API key "
            "cloud) NO se pueden generar resúmenes (núcleo). Ver INSTALL.md §2."
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


def cmd_verify(args: argparse.Namespace) -> int:
    """Corre el flujo sobre la muestra incluida y evalúa contra el control set."""
    from .acceptance import acceptance_verdict, load_control_set
    from .adapters.pdf_batch import run_batch_pdfs
    from .contract import SummaryResult
    from .control import run_control_suite
    from .workspace import Workspace

    here = Path(__file__).resolve().parent.parent.parent
    pdfs = args.pdfs or str(here / "samples" / "pdfs")
    control = args.control or str(here / "samples" / "control_set.json")
    ws = Workspace(args.workspace)
    transcriber = _build_transcriber(args.fake, args.lang)
    backend, model = _resolve_backend_model(args.backend, args.model)
    summarizer = _build_summarizer(args.fake or args.dry_run, backend, model)
    run_batch_pdfs(pdfs, ws, transcriber, summarizer, long_strategy=args.long_strategy)
    # cargar resultados y evaluar contra el set de control
    results = {}
    for f in ws.summaries_dir.glob("*.json"):
        if f.name == "report.json":
            continue
        import json

        d = json.loads(f.read_text(encoding="utf-8"))
        d.pop("_qa", None)
        results[d["doc_id"]] = SummaryResult.from_dict(d)
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

    def _add_backend_model(sp: argparse.ArgumentParser) -> None:
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
            help="modelo a usar (def: config 'model'/'cloud_model', si no "
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
    s.set_defaults(func=cmd_summarize)

    b = sub.add_parser("batch", help="procesar un lote de .txt (cola + QA)")
    b.add_argument("--in", dest="in_dir", required=True, help="directorio con .txt")
    b.add_argument("--out", dest="out_dir", required=True, help="directorio salida")
    _add_backend_model(b)
    b.add_argument("--max-retries", dest="max_retries", type=int, default=2)
    b.add_argument(
        "--dry-run", action="store_true", help="usar resumidor fake (sin modelo)"
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

    r = sub.add_parser("run", help="flujo completo desde PDFs (transcribe+resume)")
    r.add_argument("--in", dest="in_dir", required=True, help="directorio de PDFs")
    r.add_argument(
        "--workspace", required=True, help="dir de artefactos (ocr/, summaries/)"
    )
    r.add_argument(
        "--lang",
        default=get_config_value("lang", "por+eng+spa"),
        help="idioma(s) OCR Tesseract, combinables con '+' "
        "(default: por+eng+spa; ej. anadir frances: "
        "por+eng+spa+fra)",
    )
    _add_backend_model(r)
    r.add_argument(
        "--long-strategy",
        dest="long_strategy",
        default=get_config_value("long_strategy", "excerpt"),
        choices=["excerpt", "blocks", "hierarchical"],
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
    t.add_argument("--fake", action="store_true")
    t.set_defaults(func=cmd_transcribe)

    d = sub.add_parser("doctor", help="verificar dependencias de sistema/modelos")
    _add_backend_model(d)
    d.set_defaults(func=cmd_doctor)

    v = sub.add_parser("verify", help="verificar resultados sobre la muestra incluida")
    v.add_argument(
        "--workspace", default="./_verify", help="dir de artefactos de la verificación"
    )
    v.add_argument("--pdfs", default=None, help="dir de PDFs (def: muestra)")
    v.add_argument("--control", default=None, help="set de control (def: incluido)")
    v.add_argument("--lang", default="por+eng+spa")
    _add_backend_model(v)
    v.add_argument(
        "--long-strategy",
        dest="long_strategy",
        default=get_config_value("long_strategy", "excerpt"),
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
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
