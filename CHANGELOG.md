# Changelog — pdfsum

Formato basado en [Keep a Changelog](https://keepachangelog.com/); versionado
semántico. Repositorio **git local** (sin remoto); las versiones se marcan con
tags git locales.

## [0.7.1] — 2026-08-19 — Precondiciones claras
### Cambiado
- `pdfsum doctor` ahora muestra un bloque de **CAPACIDADES** (extraer / OCR /
  resumen / OCR-VLM), dejando claro que **resumir requiere Ollama + modelo**
  (núcleo), no es opcional.
- `run`, `batch`, `summarize` hacen **preflight**: si Ollama o el modelo no
  están, se detienen con un **mensaje accionable** (qué `ollama pull` correr,
  ver `doctor`/INSTALL.md) y código 2, en vez de una traza críptica.
- INSTALL.md §1 lidera con una **tabla de precondiciones por capacidad**.
### Verificado
- eval-spec `FASE6-1-PRECONDICIONES`: 6/6 criterios; 69 tests; ruff limpio.

## [0.7.0] — 2026-08-19 — Fase 6: empaquetado y reproducibilidad
### Añadido
- `pyproject.toml`: paquete instalable (`pip install -e .`) con entry point
  de consola `pdfsum` (sin dependencias Python; requisitos son de sistema).
- `adapters/doctor.py` + CLI `pdfsum doctor`: verifica poppler, tesseract
  (+idiomas), ollama y modelos; distingue requisitos duros/opcionales.
- `acceptance.py` (dominio) + CLI `pdfsum verify`: corre el flujo sobre una
  muestra incluida y evalúa contra un set de control (PASS/FAIL por cobertura,
  idioma y tipo).
- `samples/pdfs/` + `samples/control_set.json`: muestra y control incluidos.
- `INSTALL.md`: guía de instalación, verificación y distribución (git bundle/
  tarball), con la advertencia de no-determinismo del LLM.
### Verificado
- eval-spec `FASE6-EMPAQUETADO`: 12/12 criterios; 64 tests; ruff limpio.
- pip install en venv aislado; `pdfsum verify` real -> PASS (cobertura 1.00).

## [0.6.0] — 2026-08-19 — Fase 5: flujo end-to-end desde PDF
### Añadido
- `workspace.py` (dominio): almacén canónico de artefactos (ocr/, summaries/,
  report.json, lilacs.json).
- `adapters/pdf_batch.py`: `transcribe_pdfs()` (OCR con caché idempotente en
  ocr/) y `run_batch_pdfs()` (transcribe -> resume -> report desde PDFs).
- CLI `pdfsum run` (flujo completo desde PDFs) y `pdfsum transcribe`.
### Corregido
- **Gap de integración:** el producto ahora arranca desde la fuente real
  (PDFs), no desde .txt ya transcritos. La transcripción (adaptador
  OcrTranscriber, ya existente) queda cableada al CLI y al lote.
### Verificado
- eval-spec `FASE5-PDF-E2E`: 10/10 criterios; 56 tests; ruff limpio.
- End-to-end desde PDFs del piloto (escaneado+nativo) con almacén canónico.

## [0.5.0] — 2026-08-19 — Fase 4: mejora continua
### Añadido
- `chunking.py` (dominio): `split_blocks()` divide texto largo en bloques con
  cobertura total, y `summarize_in_blocks()` resume cada bloque y consolida.
- `control.py` (dominio): `term_coverage()`, `evaluate_case()` y
  `run_control_suite()` para un set de control fijo con métricas de cobertura.
- `pipeline.summarize_document(long_strategy='blocks')`: cubre TODO el texto
  en documentos gigantes (resuelve el truncado de manuales largos del piloto).
### Verificado
- eval-spec `FASE4-MEJORA`: 12/12 criterios; 49 tests; ruff limpio.
- End-to-end: manual 60375 (117k) -> 3 bloques, cobertura completa.

## [0.4.0] — 2026-08-19 — Fase 3: interfaz
### Añadido
- `review.py` (dominio): flujo de revisión humana (aprobar/rechazar/editar)
  con estados e historial; no permite aprobar con fallos QA de error salvo
  `force` (registrado).
- `export.py` (dominio): `to_lilacs()` mapea a registro LILACS **borrador**
  (tipo doc 05, título, idioma, resúmenes multilingües, descriptores
  CANDIDATOS con nota de validación DeCS/MeSH pendiente).
- `adapters/api_server.py`: API de consulta de solo lectura (http.server,
  sin dependencias): `/api/summaries`, `/api/summaries/<id>`, `/api/report`.
- CLI `pdfsum export` y `pdfsum serve`.
### Verificado
- eval-spec `FASE3-INTERFAZ`: 13/13 criterios; 40 tests; ruff limpio.
- End-to-end: export LILACS del lote real + API sirviendo consultas.

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
