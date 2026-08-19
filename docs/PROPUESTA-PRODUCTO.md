# Propuesta de producto — Resúmenes estructurados de documentos PDF

**Proyecto:** INFOMED / Intercambio BIREME
**De:** Pedro (con asistencia de agente Pi)
**Fecha:** 2026-08-19
**Estado:** propuesta para decisión del equipo
**Base:** piloto validado sobre 28 PDFs (ver `INFORME-EXPERIENCIA-Resumenes-BIREME.md`)

---

## 1. Resumen ejecutivo

El piloto demostró que podemos convertir PDFs heterogéneos (folletos, cartaces,
artículos científicos) en **resúmenes estructurados**, de forma **local, sin
coste de API y sin que los documentos salgan de la máquina**, con calidad
medida de 95–100 %. Esta propuesta describe cómo convertir esa prueba en un
**producto operable, observable y mantenible**.

La idea central: el **motor ya está validado**; el producto consiste en
**envolverlo** con enrutado inteligente, control de calidad automático,
operación por lotes y una interfaz de consulta/export. No reinventamos el
núcleo, lo industrializamos.

---

## 2. De prueba a producto: qué cambia

| Dimensión | Piloto (hoy) | Producto (objetivo) |
|---|---|---|
| **Entrada** | carpeta local `*.pdf` | ingesta reproducible (watch folder / upload / cola desde repositorio) |
| **Ejecución** | scripts bash a mano | servicio con **cola de trabajos** (1 doc = 1 job), reintentos, idempotencia |
| **Decisión** | umbrales fijos en el script | **clasificador de tipo/idioma/tamaño** que enruta a plantilla y estrategia |
| **Salida** | `.md` sueltos | almacén estructurado (JSON + MD) + **API de consulta** + export a catalogación (LILACS/BVS) |
| **Calidad** | muestreo manual | **gates automáticos** por documento (esquema completo, sin refusal, cobertura mínima) |
| **Operación** | ninguna | logs, métricas, coste/tiempo por doc, alertas, panel de revisión |

---

## 3. Arquitectura propuesta

```
        ┌─────────────┐
Ingesta │  API / watch │──▶ cola de jobs (SQLite/Redis)
        └─────────────┘         │
                                ▼
             ┌──────────────────────────────────────┐
             │  WORKER (1 doc → pipeline)            │
             │  0. clasificar: nativo/escaneado,     │
             │     idioma, tipo (art/manual/folleto),│
             │     tamaño → estrategia + plantilla   │
             │  1. transcribir (pdftotext | OCR      │
             │     híbrido Tesseract↔VLM)            │
             │  2. resumir (LLM local, plantilla     │
             │     por tipo, idioma del doc)         │
             │  3. extraer abstracts verbatim        │
             │  4. QA gates (esquema/refusal/cobert.)│
             └──────────────────────────────────────┘
                                │
                                ▼
        almacén (JSON + MD)  ──▶ API de consulta / export DeCS-LILACS ──▶ panel
```

**Principio de diseño (hexagonal / DDD):** el **dominio** (clasificar, resumir,
evaluar) no depende de los **adaptadores** (Ollama, Tesseract, cola, API). Así
podemos cambiar de modelo local a cloud, o de Tesseract a otro OCR, sin tocar el
núcleo. Los pasos 1–3 son exactamente lo que ya validó el piloto.

---

## 4. Decisiones que debemos tomar (equipo)

1. **Alcance del despliegue:**
   - **(a) Herramienta interna** — CLI + servicio en una máquina del equipo,
     salida a carpeta/almacén. Rápido, bajo coste, poco riesgo.
   - **(b) Servicio con API** — otros sistemas envían PDFs y reciben resúmenes.
     Más trabajo, más valor de integración.
2. **Local vs cloud (o híbrido):** el piloto es 100 % local (confidencialidad,
   coste cero). ¿Se mantiene local, o se permite una **pasada cloud opcional**
   para escaneos difíciles / mayor precisión en nombres técnicos? Requiere
   definir **qué documentos pueden salir** de la máquina.
3. **Persistencia y catalogación:** ¿basta con `.md`+`.json`, o se integra con
   el flujo BIREME (**DeCS/MeSH**, export a **LILACS/BVS**)? Esto define el valor
   real del producto en el ecosistema BIREME.
4. **Humano en el bucle:** ¿publicación automática o **revisión/edición** antes
   de catalogar? Recomendación: revisión al principio, automatizar cuando las
   métricas lo respalden.

---

## 5. Roadmap por fases (incremental, cada fase entrega valor)

### Fase 0 — Consolidar el motor *(en curso)*
Empaquetar los scripts del piloto en un **módulo** con configuración (idiomas,
modelos, umbrales), **contrato de salida JSON estable**, y tests. Sin esto, todo
lo demás es frágil.
> **Entregable:** librería `pdfsum` + CLI + contrato JSON + tests + eval-spec.

### Fase 1 — Enrutado inteligente
Clasificador de **tipo / idioma / tamaño** → selección de **plantilla** (§3.1 del
informe: artículo IMRAD, manual, divulgación) y **estrategia de porción**
(portada/índice/intro para manuales; abstract+cuerpo para artículos). Resuelve
los 2 casos truncados del piloto y estandariza salidas.

### Fase 2 — Operación por lotes
Cola de jobs, idempotencia, reintentos, **QA gates automáticos**, logs y
métricas (tiempo/coste por doc). Aquí pasa de "script" a "servicio operable".

### Fase 3 — Interfaz
API de consulta y/o **panel de revisión** (aprobar/editar resúmenes) + export al
formato de catalogación BIREME (DeCS/MeSH, LILACS/BVS).

### Fase 4 — Mejora continua
Set de control fijo con métricas de cobertura por lote; evaluación de la pasada
cloud opcional; reentrenamiento de umbrales con datos reales.

---

## 6. Método de trabajo (EDD)

Cada fase arranca con su **eval-spec** (criterios ejecutables), y los tests
corresponden 1:1 a esos criterios. Ejemplos de criterios:

- Todo documento produce un resumen con **esquema completo** (sin campos vacíos
  obligatorios).
- **0 refusals** y 0 respuestas que se dirijan al usuario.
- **Idioma de salida = idioma del documento** (verificado).
- **Artículo científico → plantilla A** (structured abstract).
- **Cobertura ≥ umbral** contra un ground-truth fijo.
- Los **abstracts de origen** multilingües se preservan verbatim.

eval-spec → branch → tests → código → `make check` verde → `merge --no-ff` a
master → tag. Sin commits directos a `master` (hook global). **Estado actual:**
repositorio **git local** (sin remoto). El salto a un remoto con PR/CI real es
parte de las Fases 2-3 y una decisión del equipo (ver §4.1). Detalle del flujo
local en `CONTRIBUTING.md`.

---

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Calidad OCR variable en escaneos difíciles | fallback VLM ya probado; pasada cloud opcional para lotes críticos |
| Modelos locales limitados por hardware (8 GB) | contrato desacoplado del modelo; permite escalar a máquina mayor o cloud |
| Documentos muy largos | estrategia por tipo (Fase 1) + resumen por bloques |
| Deriva de calidad con el tiempo | set de control fijo + métricas por lote (Fase 4) |
| Dependencia de una sola persona | módulo documentado, tests, eval-specs; reproducible por el equipo |

---

## 8. Recomendación

Arrancar por **Fase 0 + Fase 1** como primer entregable real: el motor
consolidado con enrutado por tipo. Es lo que convierte el piloto en algo
*confiable y estandarizado*, y ya resuelve las limitaciones documentadas. Las
fases 2–3 dependen de la decisión de **alcance** (§4.1: interno vs servicio).

**Estado actual:** Fase 0 **en curso** (motor + contrato JSON + tests).
