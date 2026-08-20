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

from .contract import SummaryResult
from .pipeline import summarize_document


def _build_summarizer(dry_run: bool, model: str):
    if dry_run:
        from .adapters.fake_summarizer import FakeSummarizer
        return FakeSummarizer()
    from .adapters.ollama_summarizer import OllamaSummarizer
    return OllamaSummarizer(model=model)


def cmd_summarize(args: argparse.Namespace) -> int:
    text = Path(args.text).read_text(encoding="utf-8", errors="replace")
    doc_id = args.doc_id or Path(args.text).stem
    summarizer = _build_summarizer(args.dry_run, args.model)
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
    summarizer = _build_summarizer(args.dry_run, args.model)
    report = run_batch(
        in_dir=args.in_dir, out_dir=args.out_dir, summarizer=summarizer,
        max_retries=args.max_retries,
    )
    m = report["metrics"]
    print(f"lote: {m['total']} docs | ok={m['ok']} fallos={m['con_fallos']} "
          f"| tipos={m['por_tipo']} idiomas={m['por_idioma']} "
          f"| tiempo_medio={m['tiempo_medio']}s")
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


def cmd_serve(args: argparse.Namespace) -> int:
    from .adapters.api_server import serve
    serve(args.batch_dir, host=args.host, port=args.port)
    return 0


def _build_transcriber(fake: bool, lang: str):
    if fake:
        from .adapters.fake_transcriber import FakeTranscriber
        return FakeTranscriber(text="texto de prueba " * 20, pages=1)
    from .adapters.ocr_transcriber import OcrTranscriber
    return OcrTranscriber(lang=lang)


def cmd_run(args: argparse.Namespace) -> int:
    """Flujo completo desde PDFs: transcribe (cache) -> resume -> report."""
    from .adapters.pdf_batch import run_batch_pdfs
    from .workspace import Workspace
    ws = Workspace(args.workspace)
    transcriber = _build_transcriber(args.fake, args.lang)
    summarizer = _build_summarizer(args.fake or args.dry_run, args.model)
    report = run_batch_pdfs(
        args.in_dir, ws, transcriber, summarizer,
        long_strategy=args.long_strategy,
    )
    m = report["metrics"]
    print(f"run: {m['total']} PDFs | ok={m['ok']} fallos={m['con_fallos']} "
          f"| tipos={m['por_tipo']} | ocr={ws.ocr_dir} "
          f"| resumenes={ws.summaries_dir}")
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdfsum", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summarize", help="resumir un texto ya transcrito")
    s.add_argument("--text", required=True, help="ruta a .txt (transcripción)")
    s.add_argument("--doc-id", dest="doc_id", default=None)
    s.add_argument("--lang", default=None, help="forzar idioma (pt/es/en/...)")
    s.add_argument("--pages", type=int, default=1)
    s.add_argument("--model", default="qwen2.5:7b")
    s.add_argument("--dry-run", action="store_true",
                   help="usar resumidor fake (sin modelo)")
    s.add_argument("--out", default=None, help="escribir JSON a archivo")
    s.set_defaults(func=cmd_summarize)

    b = sub.add_parser("batch", help="procesar un lote de .txt (cola + QA)")
    b.add_argument("--in", dest="in_dir", required=True, help="directorio con .txt")
    b.add_argument("--out", dest="out_dir", required=True, help="directorio salida")
    b.add_argument("--model", default="qwen2.5:7b")
    b.add_argument("--max-retries", dest="max_retries", type=int, default=2)
    b.add_argument("--dry-run", action="store_true",
                   help="usar resumidor fake (sin modelo)")
    b.set_defaults(func=cmd_batch)

    e = sub.add_parser("export", help="exportar lote a registros LILACS (borrador)")
    e.add_argument("--in", dest="in_dir", required=True, help="dir del lote")
    e.add_argument("--out", required=True, help="archivo .json de salida")
    e.set_defaults(func=cmd_export)

    sv = sub.add_parser("serve", help="API de consulta de solo lectura del lote")
    sv.add_argument("--batch-dir", dest="batch_dir", required=True)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(func=cmd_serve)

    r = sub.add_parser("run", help="flujo completo desde PDFs (transcribe+resume)")
    r.add_argument("--in", dest="in_dir", required=True, help="directorio de PDFs")
    r.add_argument("--workspace", required=True, help="dir de artefactos (ocr/, summaries/)")
    r.add_argument("--lang", default="por", help="idioma OCR Tesseract (por/spa/eng)")
    r.add_argument("--model", default="qwen2.5:7b")
    r.add_argument("--long-strategy", dest="long_strategy", default="excerpt",
                   choices=["excerpt", "blocks"])
    r.add_argument("--dry-run", action="store_true",
                   help="resumidor fake (OCR real)")
    r.add_argument("--fake", action="store_true",
                   help="transcriber Y resumidor fake (sin poppler/ollama)")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("transcribe", help="solo transcribir PDFs a ocr/*.txt")
    t.add_argument("--in", dest="in_dir", required=True, help="directorio de PDFs")
    t.add_argument("--workspace", required=True)
    t.add_argument("--lang", default="por")
    t.add_argument("--fake", action="store_true")
    t.set_defaults(func=cmd_transcribe)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
