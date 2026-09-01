# Estado del producto pdfsum

**Actualizado:** 2026-09-01 · **Versión:** 0.13.0 ·
**Repo:** GitHub `idourra/pdf-summarizer` (rama → PR → CI → merge → tag)

## Roadmap y avance

| Fase | Descripción | Estado | Versión | Eval-spec |
|---|---|---|---|---|
| 0 | Motor consolidado (dominio + contrato JSON + puertos) | ✅ hecho | 0.1.0 | `FASE0-MOTOR` 11/11 |
| 1 | Enrutado inteligente (porción por tipo + Transcriber) | ✅ hecho | 0.2.0 | `FASE1-ENRUTADO` 12/12 |
| 2 | Operación por lotes (cola, QA gates, métricas) | ✅ hecho | 0.3.0 | `FASE2-LOTES` 13/13 |
| 3 | Interfaz (API + revisión + export LILACS) | ✅ hecho | 0.4.0 | `FASE3-INTERFAZ` 13/13 |
| 4 | Mejora continua (set de control, resumen por bloques) | ✅ hecho | 0.5.0 | `FASE4-MEJORA` 12/12 |
| 5 | Flujo E2E desde PDF + almacén canónico | ✅ hecho | 0.6.0 | `FASE5-PDF-E2E` 10/10 |
| 6 | Empaquetado y reproducibilidad por terceros | ✅ hecho | 0.7.x | `FASE6-EMPAQUETADO` 12/12 |
| 7 | Paridad OCR piloto (fallback VLM) | ✅ hecho | 0.8.0 | `FASE7-OCR-VLM` 8/8 |
| 8 | Segmentación de página (columnas/bloques) | ✅ hecho | 0.9.0 | `FASE8-SEGMENTACION` 8/8 |
| 9 | OCR multilenguaje (por+eng+spa combinables) | ✅ hecho | 0.9.x | `FASE9-OCR-MULTILANG` |
| 10 | Resumen jerárquico por capítulos | ✅ hecho | 0.10.0 | `FASE10-JERARQUICO` |
| 11 | Migración a uv (gestor moderno Python) | ✅ hecho | 0.11.0 | `FASE11-UV` |
| 12 | Distribución moderna (hatchling + uv build + PyPI) | ✅ hecho | 0.12.0 | `FASE12-DISTRIBUCION` |
| 13 | Docker + Ollama runtime configurable | ✅ hecho | 0.13.0 | `FASE13-DOCKER-OLLAMA` |
| 14 | Backends cloud (openai/openrouter/anthropic) | ✅ hecho | 0.13.0 | `FASE14-BACKENDS-CLOUD` |
| 15 | Registros bibliográficos BIBFRAME (JSON-LD) | ✅ hecho | 0.13.0 | `FASE15-BIBFRAME` |
| — | Observabilidad durable (events/infra/report 3.0) | ✅ hecho | 0.13.0 | PR #6/#9 |

**Roadmap completo + integración E2E.** El producto arranca desde la **fuente
real (PDFs)** y cubre el ciclo completo hasta la catalogação, con
observabilidad durable del lote y salida bibliográfica BIBFRAME/LILACS.

## Flujo y almacén (desde la fuente)

```
<dir-pdfs>/*.pdf
   |  pdfsum run --in <dir-pdfs> --workspace <ws> [--backend ollama|openai|openrouter|anthropic] [--vlm-model <m>]
   v
<ws>/ocr/<doc_id>.txt            transcripciones (OCR/nativo, cacheadas)
<ws>/summaries/<doc_id>.json     resúmenes estructurados + _qa
<ws>/summaries/report.json       report v3.0 (métricas, run_id, progreso; escritura atómica)
<ws>/summaries/events.jsonl      eventos del lote (sincronizados por evento)
<ws>/summaries/infrastructure.jsonl  muestras de CPU/RAM/disco/GPU
<ws>/bibframe/<doc_id>.bibframe.json registros BIBFRAME JSON-LD (pdfsum bibframe)
<ws>/lilacs.json                 export de catalogação (pdfsum export)
```

## Qué hace hoy (0.13.0)

1. **Clasifica** origen (nativo/escaneado), **idioma** y **tipo**
   (artículo/manual/divulgación) y **selecciona la porción** según el tipo.
2. **Transcribe** con OCR híbrido nativo+Tesseract (multilenguaje `por+eng+spa`,
   segmentación de columnas) y fallback VLM configurable (`--vlm-model`).
3. **Resume** en el idioma del documento con la plantilla del tipo, con
   estrategias para documentos largos (`excerpt`/`blocks`/`hierarchical`).
4. **Backends de resumen intercambiables**: Ollama local (default) o cloud
   (`openai`/`openrouter`/`anthropic`) vía flag/env/config; API keys solo por
   variables de entorno.
5. **Lotes idempotentes** con QA gates, métricas y **observabilidad durable**
   (report.json 3.0 atómico, events.jsonl, infrastructure.jsonl, métricas GPU
   opt-in). `batch`/`run` devuelven `rc=1` si hay fallos de procesamiento.
6. **Revisión humana**, **export LILACS** (descriptores candidatos, validación
   DeCS pendiente), **registros BIBFRAME 2.x JSON-LD** por documento
   (`pdfsum bibframe`) y **API de consulta** local (`pdfsum serve`).
7. **Distribución**: PyPI (`pip install pdfsum` / `uv`), Docker + Compose
   (modos local/GPU/cloud), wrapper `bin/pdfsum-docker`, CI completo
   (lint+format+tests+arquitectura+build) y publicación automática por tag.

## Pendientes / decisiones abiertas

1. **Traspaso a la célula BIREME**: PR #7 (`docs/PLAN-TRASPASO-BIREME.md`),
   6 fases; requiere designar 2+ maintainers y validar cronograma.
2. **Validación DeCS/MeSH real** de los descriptores candidatos del export
   LILACS/BIBFRAME (hoy quedan marcados como candidatos/draft).
3. Alcance a futuro: herramienta interna (CLI+servicio local) vs servicio
   con API multiusuario.

Ver detalle en `docs/PROPUESTA-PRODUCTO.md` y `docs/PLAN-TRASPASO-BIREME.md`
(PR #7).

## Cómo se versiona

Rama de feature → PR → CI verde → merge a `master` → tag `vX.Y.Z` (dispara
build + publicación a Test PyPI/PyPI y GitHub Release vía `publish.yml`).
Detalle en `CONTRIBUTING.md`. Disciplina EDD: eval-spec en `evals/` antes de
implementar cada fase.
