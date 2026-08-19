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
  contract.py    # DOMINIO: tipos + PUERTO Summarizer (Protocol) + contrato JSON
  classify.py    # DOMINIO: origen (nativo/escaneado), idioma, tipo -> plantilla
  templates.py   # DOMINIO: plantillas A (artículo/IMRAD), B (manual), C (folleto)
  abstracts.py   # DOMINIO: extracción verbatim de RESUMO/ABSTRACT/RESUMEN...
  pipeline.py    # DOMINIO: orquesta clasificación + resumen + abstracts
  adapters/      # EXTERNO: implementan el puerto (Ollama real, fake para tests)
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

- **Fase 0 (motor):** ✅ completada — 11/11 criterios del eval-spec
  (`evals/eval-spec-fase0-motor.yaml`).
- **Fase 1 (enrutado inteligente):** pendiente — estrategia de porción por tipo
  y adaptador de transcripción/OCR (integrar `ocr_pipeline.sh` del piloto).
- Ver roadmap completo en `docs/PROPUESTA-PRODUCTO.md`.
