# pdfsum — motor de resúmenes estructurados de PDF

Producto derivado del piloto BIREME–INFOMED. **Fase 0: motor consolidado.**

## Qué es

Un módulo Python que convierte el texto de un documento (ya transcrito) en un
**resumen estructurado** conforme a un **contrato JSON estable**, eligiendo la
**plantilla según el tipo de documento** y respondiendo **en el idioma del
documento**, preservando los **resúmenes de origen multilingües** verbatim.

## Arquitectura (hexagonal)

```
src/pdfsum/
  contract.py    # DOMINIO: tipos + PUERTOS Summarizer/Transcriber + contrato JSON
  classify.py    # DOMINIO: origen (nativo/escaneado), idioma, tipo -> plantilla
  templates.py   # DOMINIO: plantillas A (artículo/IMRAD), B (manual), C (folleto)
  abstracts.py   # DOMINIO: extracción verbatim de RESUMO/ABSTRACT/RESUMEN...
  excerpt.py     # DOMINIO: estrategia de porción por tipo (no corte ciego)
  pipeline.py    # DOMINIO: orquesta clasificación + porción + resumen + abstracts
  adapters/      # EXTERNO: Ollama, OCR (poppler+Tesseract), fakes para tests
  cli.py         # CLI
```

Regla de dependencia: **el dominio no importa adaptadores** (verificado por
`test_architecture.py` vía AST). Cambiar de modelo local a cloud = nuevo
adaptador, sin tocar el núcleo.

## Uso

```bash
# resumen real (requiere Ollama + qwen2.5:7b)
PYTHONPATH=src python3 -m pdfsum.cli summarize \
    --text transcripcion.txt --pages 4 --out resumen.json

# dry-run sin modelo (contrato + clasificación, para probar el flujo)
PYTHONPATH=src python3 -m pdfsum.cli summarize --text transcripcion.txt --dry-run

# lote: directorio de .txt con cola idempotente + QA gates
PYTHONPATH=src python3 -m pdfsum.cli batch --in ./_ocr_out --out ./_resumenes
# -> un .json por doc (con bloque _qa) + report.json (métricas del lote)

# export a registros LILACS (borrador para revisión humana)
PYTHONPATH=src python3 -m pdfsum.cli export --in ./_resumenes --out lilacs.json

# API de consulta local (solo lectura) sobre el lote
PYTHONPATH=src python3 -m pdfsum.cli serve --batch-dir ./_resumenes --port 8765
# GET /api/summaries | /api/summaries/<doc_id> | /api/report
```

Salida: JSON con `doc_id`, `idioma_principal`, `tipo_documento`, `plantilla`,
`secciones`, `idiomas_resumo_origem`, `abstracts_origem`, `meta`.

## Desarrollo

```bash
make lint     # ruff
make test     # unittest (criterios del eval-spec)
make check    # lint + test
```

## Estado

- **Fase 0 (motor):** ✅ completada — 11/11 criterios
  (`evals/eval-spec-fase0-motor.yaml`).
- **Fase 1 (enrutado inteligente):** ✅ completada — 12/12 criterios
  (`evals/eval-spec-fase1-enrutado.yaml`). Estrategia de porción por tipo
  (artículo: abstract+intro+conclusiones; manual: portada+índice+intro;
  folleto: completo) + puerto `Transcriber` con adaptador OCR (poppler+Tesseract).
  Resuelve el truncado de manuales largos del piloto.
- **Fase 2 (operación por lotes):** ✅ completada — 13/13 criterios
  (`evals/eval-spec-fase2-lotes.yaml`). Cola idempotente con reintentos, QA
  gates automáticos (esquema/refusal/idioma/abstracts), métricas y `report.json`.
  CLI `pdfsum batch`.
- **Fase 3 (interfaz):** ✅ completada — 13/13 criterios
  (`evals/eval-spec-fase3-interfaz.yaml`). Flujo de revisión, export LILACS
  (borrador) y API de consulta local. CLI `pdfsum export` / `pdfsum serve`.
- **Fase 4 (mejora continua):** ✅ completada — 12/12 criterios
  (`evals/eval-spec-fase4-mejora.yaml`). Resumen por bloques (documentos
  gigantes completos) + set de control con métricas de cobertura.
- **Roadmap completo:** las 5 fases (0-4) implementadas y verificadas.
- Ver `docs/ESTADO.md` y `docs/PROPUESTA-PRODUCTO.md`.
