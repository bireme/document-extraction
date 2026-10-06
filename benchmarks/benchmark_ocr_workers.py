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
from threading import Lock
from unittest.mock import patch

from pdfsum.adapters import hybrid_ocr
from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber
from pdfsum.adapters.vlm_ocr import VlmPageOCR


class LegacyTextTranscriber(HybridOcrTranscriber):
    """Referencia local: repite Tesseract como antes de reutilizar el TSV."""

    def _ocr_page(self, img):
        text, conf, words, info = super()._ocr_page(img)
        if not info["vlm"] and not info["vlm_rejected"]:
            text = hybrid_ocr._run(
                ["tesseract", str(img), "stdout", "-l", self.lang, "--psm", "1"]
            )
        return text, conf, words, info


def measure(tx, pdf):
    """Contadores exclusivos del benchmark; no modifica report.json."""
    counts = {"llamadas_tsv": 0, "llamadas_texto": 0, "regiones": 0}
    lock = Lock()
    original = hybrid_ocr._run

    def run(cmd, timeout=120):
        if cmd[0] == "tesseract":
            key = "llamadas_tsv" if cmd[-1] == "tsv" else "llamadas_texto"
            with lock:
                counts[key] += 1
        return original(cmd, timeout=timeout)

    def event(name, **fields):
        if name == "ocr_pagina_completada":
            with lock:
                counts["regiones"] += fields["regiones"]

    tx.set_event_sink(event)
    with patch.object(hybrid_ocr, "_run", side_effect=run):
        started = time.perf_counter()
        result = tx.transcribe(str(pdf))
        elapsed = time.perf_counter() - started
    counts["llamadas_tesseract"] = counts["llamadas_tsv"] + counts["llamadas_texto"]
    return result, elapsed, counts


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
    parser.add_argument("--workers", nargs="+", type=positive, default=[1, 2, 4])
    parser.add_argument(
        "--compare-tsv",
        action="store_true",
        help="comparar dos llamadas con reutilización TSV",
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
            order = args.workers
            shift = repeat % len(order)
            for workers in order[shift:] + order[:shift]:
                modes = [("tsv", HybridOcrTranscriber)]
                if args.compare_tsv:
                    modes.insert(0, ("dos_llamadas", LegacyTextTranscriber))
                if repeat % 2:
                    modes.reverse()
                for mode, transcriber in modes:
                    tx = transcriber(
                        lang=args.lang,
                        vlm=vlm,
                        ocr_workers=workers,
                        vlm_workers=args.vlm_workers,
                    )
                    result, elapsed, counts = measure(tx, pdf)
                    digest = hashlib.sha256(result.text.encode("utf-8")).hexdigest()
                    reference = baseline.setdefault(
                        (index, mode), (digest, result.pages_detail)
                    )
                    normalized = " ".join(result.text.split())
                    token_digest = hashlib.sha256(
                        normalized.encode("utf-8")
                    ).hexdigest()
                    token_reference = baseline.setdefault(
                        (index, "tokens"), token_digest
                    )
                    stem = f"{index}-{pdf.stem}-r{repeat + 1}-w{workers}-{mode}"
                    (args.out / f"{stem}.txt").write_text(result.text, encoding="utf-8")
                    record = {
                        "pdf": str(pdf),
                        "modo": mode,
                        **counts,
                        "texto_normalizado_sha256": token_digest,
                        "palabras_iguales_referencia": token_digest == token_reference,
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
