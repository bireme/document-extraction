"""CLI del motor pdfsum.

Fase 0: subcomando `summarize` sobre un texto ya transcrito, con `--dry-run`
(usa el resumidor fake, sin modelo) o resumidor real (Ollama) por defecto.
La transcripción/OCR (Paso 1) se integrará como adaptador en fases siguientes;
aquí el foco es el contrato de salida y el pipeline de dominio.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
