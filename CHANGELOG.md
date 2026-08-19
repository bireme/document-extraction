# Changelog — pdfsum

Formato basado en [Keep a Changelog](https://keepachangelog.com/); versionado
semántico. Repositorio **git local** (sin remoto); las versiones se marcan con
tags git locales.

## [0.3.0] — 2026-08-19 — Fase 2: operación por lotes
### Añadido
- `qa.py` (dominio): QA gates que validan cada resultado contra el contrato
  (schema, refusal, idioma, abstracts preservados) -> `QAReport`.
- `metrics.py` (dominio): `batch_metrics()` agrega total/ok/fallos, por tipo,
  por idioma, gates fallados y tiempos.
- `queue.py` (dominio): `JobQueue` con idempotencia (doc_id+hash) y reintentos,
  sobre el puerto `JobStore`.
- Puerto `JobStore` + adaptadores `MemoryJobStore` y `FileJobStore`.
- `adapters/batch_runner.py`: orquesta lote (cola+QA+métricas), escribe un
  .json por doc + `report.json`.
- CLI `pdfsum batch --in <dir> --out <dir>`.
### Verificado
- eval-spec `FASE2-LOTES`: 13/13 criterios; 30 tests; ruff limpio.
- End-to-end: lote de 3 docs -> 3/3 QA ok; re-ejecución idempotente (0.1s).

## [0.2.0] — 2026-08-19 — Fase 1: enrutado inteligente
### Añadido
- `excerpt.py` (dominio): estrategia de porción por tipo de documento
  (artículo → abstract+intro+conclusiones; manual → portada+índice+intro;
  folleto → completo). Elimina el corte ciego por offset del piloto.
- Puerto `Transcriber` + `TranscriptResult` en `contract.py`.
- Adaptadores `OcrTranscriber` (poppler+Tesseract) y `FakeTranscriber`.
- `pipeline.summarize_pdf()`: pipeline completo transcribe+resume vía puertos.
- `meta` del resultado registra la estrategia de porción usada.
### Cambiado
- `classify_type` prioriza manual/libro (índice + ≥10 págs) sobre artículo,
  resolviendo manuales largos con marcadores IMRAD internos mal clasificados.
### Verificado
- eval-spec `FASE1-ENRUTADO`: 12/12 criterios; 20 tests; ruff limpio.
- End-to-end: manual `60391` (antes truncado/refusal) → plantilla B correcta.

## [0.1.0] — 2026-08-19 — Fase 0: motor consolidado
### Añadido
- Arquitectura hexagonal: dominio (`contract`, `classify`, `templates`,
  `abstracts`, `pipeline`) desacoplado de adaptadores.
- Contrato JSON estable `SummaryResult` v1.0.
- Puerto `Summarizer` + adaptadores Ollama y fake.
- Plantillas por tipo (A artículo/IMRAD, B manual, C divulgación).
- Detección de idioma + extracción verbatim de abstracts multilingües.
- CLI con `--dry-run`. Makefile (lint+test).
### Verificado
- eval-spec `FASE0-MOTOR`: 11/11 criterios; 10 tests; ruff limpio.
