"""Compara transcripción completa con 1, 2 y 4 workers, sin caché de pdfsum.

Uso desde el repositorio:
  PYTHONPATH=src python benchmarks/benchmark_ocr_workers.py \
      --out /tmp/ocr-benchmark --warmup documentos/*.pdf

Añadir --vlm-model qwen3-vl:8b-instruct para medir el fallback real.
Sin esa opción se mide Tesseract, sin requerir Ollama ni GPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber
from pdfsum.adapters.vlm_ocr import VlmPageOCR


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("debe ser un entero positivo")
    return number


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument(
        "--out", required=True, type=Path, help="directorio de resultados"
    )
    parser.add_argument(
        "--repeats", type=positive, default=3, help="repeticiones por configuración"
    )
    parser.add_argument("--lang", default="por+eng+spa")
    parser.add_argument(
        "--vlm-model", default=None, help="habilitar VLM con este modelo"
    )
    parser.add_argument("--vlm-workers", type=positive, default=1)
    parser.add_argument(
        "--warmup", action="store_true", help="transcribir una vez antes de medir"
    )
    args = parser.parse_args(argv)
    if not shutil.which("tesseract"):
        parser.error("falta herramienta requerida: tesseract")
    if any(not pdf.is_file() for pdf in args.pdfs):
        parser.error("todos los PDFs deben existir")
    args.out.mkdir(parents=True, exist_ok=True)
    vlm = VlmPageOCR(model=args.vlm_model) if args.vlm_model else None
    records = []
    baseline = {}
    for index, pdf in enumerate(args.pdfs, 1):
        if args.warmup:
            HybridOcrTranscriber(lang=args.lang, vlm=vlm, ocr_workers=1).transcribe(
                str(pdf)
            )
        for repeat in range(args.repeats):
            # Rotar el orden para reducir el sesgo de cachés y calentamiento.
            order = [1, 2, 4]
            shift = repeat % len(order)
            for workers in order[shift:] + order[:shift]:
                tx = HybridOcrTranscriber(
                    lang=args.lang,
                    vlm=vlm,
                    ocr_workers=workers,
                    vlm_workers=args.vlm_workers,
                )
                started = time.perf_counter()
                result = tx.transcribe(str(pdf))
                elapsed = time.perf_counter() - started
                digest = hashlib.sha256(result.text.encode("utf-8")).hexdigest()
                reference = baseline.setdefault(index, (digest, result.pages_detail))
                stem = f"{index}-{pdf.stem}-r{repeat + 1}-w{workers}"
                (args.out / f"{stem}.txt").write_text(result.text, encoding="utf-8")
                record = {
                    "pdf": str(pdf),
                    "repeticion": repeat + 1,
                    "ocr_workers": workers,
                    "vlm_workers": args.vlm_workers,
                    "vlm_model": args.vlm_model,
                    "lang": args.lang,
                    "segundos": round(elapsed, 6),
                    "pages": result.pages,
                    "source_kind": result.source_kind.value,
                    "texto_sha256": digest,
                    "texto_igual_secuencial": digest == reference[0],
                    "detalle_igual_secuencial": result.pages_detail == reference[1],
                    "pages_detail": result.pages_detail,
                }
                records.append(record)
                print(json.dumps(record, ensure_ascii=False), flush=True)
                (args.out / "resultados.json").write_text(
                    json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )


if __name__ == "__main__":
    main()
