# Estado del producto pdfsum

**Actualizado:** 2026-08-19 · **Versión:** 0.7.0 · **Repo:** git local (sin remoto)

## Roadmap y avance

| Fase | Descripción | Estado | Versión | Eval-spec |
|---|---|---|---|---|
| 0 | Motor consolidado (dominio + contrato JSON + puertos) | ✅ hecho | 0.1.0 | `FASE0-MOTOR` 11/11 |
| 1 | Enrutado inteligente (porción por tipo + Transcriber) | ✅ hecho | 0.2.0 | `FASE1-ENRUTADO` 12/12 |
| 2 | Operación por lotes (cola, QA gates, métricas) | ✅ hecho | 0.3.0 | `FASE2-LOTES` 13/13 |
| 3 | Interfaz (API + revisión + export LILACS) | ✅ hecho | 0.4.0 | `FASE3-INTERFAZ` 13/13 |
| 4 | Mejora continua (set de control, resumen por bloques) | ✅ hecho | 0.5.0 | `FASE4-MEJORA` 12/12 |

| 5 | Flujo E2E desde PDF + almacén canónico | ✅ hecho | 0.6.0 | `FASE5-PDF-E2E` 10/10 |
| 6 | Empaquetado y reproducibilidad por terceros | ✅ hecho | 0.7.0 | `FASE6-EMPAQUETADO` 12/12 |

**Roadmap completo + integración E2E.** El producto arranca desde la **fuente
real (PDFs)** y cubre el ciclo completo hasta la catalogação.

## Flujo y almacén (desde la fuente)

```
<dir-pdfs>/*.pdf
   |  pdfsum run --in <dir-pdfs> --workspace <ws>
   v
<ws>/ocr/<doc_id>.txt          transcripciones (OCR/nativo, cacheadas)
<ws>/summaries/<doc_id>.json   resúmenes estructurados + _qa
<ws>/summaries/report.json     métricas del lote (por tipo/idioma/origen)
<ws>/lilacs.json               export de catalogação (pdfsum export)
```

## Qué hace hoy (0.3.0)

Dado el texto de un documento (o un PDF vía adaptador de transcripción):

1. **Clasifica** origen (nativo/escaneado), **idioma** y **tipo**
   (artículo/manual/divulgación).
2. **Selecciona la porción** a resumir según el tipo (no corta a ciegas).
3. **Resume** en el idioma del documento con la **plantilla** del tipo
   (A: structured abstract IMRAD; B: manual; C: divulgación).
4. **Preserva** los resúmenes de origen multilingües verbatim.
5. Emite un **JSON con contrato estable** (`SummaryResult` v1.0).

Y por **lotes** (`pdfsum batch`):

6. **Cola idempotente** con reintentos (no reprocesa docs ya hechos).
7. **QA gates** automáticos por doc (esquema, refusal, idioma, abstracts).
8. **Métricas + report.json** del lote (por tipo/idioma, calidad, tiempos).

Y para **cerrar el ciclo** (Fase 3):

9. **Revisión humana**: aprobar/rechazar/editar (no aprueba con fallos QA de
   error salvo forzado registrado).
10. **Export LILACS** (`pdfsum export`): registro borrador con tipo, título,
    resúmenes multilingües y descriptores candidatos (validación DeCS pendiente).
11. **API de consulta** (`pdfsum serve`): `/api/summaries`, `/api/summaries/<id>`,
    `/api/report` (solo lectura, local, sin dependencias).

Y para **documentos gigantes + calidad** (Fase 4):

12. **Resumen por bloques** (`long_strategy='blocks'`): cubre TODO el texto de
    manuales largos (divide + consolida), sin truncado.
13. **Set de control** con métricas de cobertura de términos, idioma y tipo
    para seguimiento de calidad por lote.

## Alineación con la propuesta de producto

- **Dominio hexagonal** desacoplado de adaptadores → permite cambiar modelo
  local↔cloud sin tocar el núcleo (decisión §4.2 de la propuesta).
- **Plantillas por tipo** (§3.1 del informe) → salidas normalizadas, base para
  export a catalogación BIREME (DeCS/MeSH, LILACS/BVS) en Fase 3.
- **Contrato JSON** → frontera estable para la cola de jobs y la API (Fases 2-3).

## Decisiones pendientes (equipo)

1. Alcance: herramienta interna (CLI+servicio) vs servicio con API.
2. Local vs cloud opcional para escaneos difíciles.
3. Integración con catalogación BIREME (¿export DeCS/LILACS?).
4. Humano en el bucle (revisión antes de publicar).

Ver detalle en `docs/PROPUESTA-PRODUCTO.md`.

## Cómo se versiona (local)

Sin remoto ni PRs: ramas de feature → `merge --no-ff` a master → `git tag`.
Detalle en `CONTRIBUTING.md`. Historial y tags dan la trazabilidad.
