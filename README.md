# pdfsum — motor de resúmenes estructurados de PDF

Producto derivado del piloto BIREME–INFOMED. **Versión actual: 0.11.0**
(flujo completo desde PDF: OCR híbrido con segmentación + resumen jerárquico
con coexistencia de estrategias + QA + export LILACS + API).

> 🚀 **Guía rápida de uso (1 página, con ejemplos ejecutables): [`GUIA-USO.md`](GUIA-USO.md)**

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

## ⚙️ Requisitos Críticos (ANTES de instalar)

**IMPORTANTE**: pdfsum requiere un **Summarizer** configurado. Elige UNO:

### ✅ Opción A: Modelos Locales con Ollama (RECOMENDADO)

**Requisitos hardware:**
- GPU ≥ **8 GB VRAM** (ej: RTX 5060, RTX 4060, etc.)
- Ollama instalado y ejecutándose: `ollama serve`
- Modelos descargados:
  ```bash
  ollama pull qwen2.5:7b          # ~6.3 GB (esencial)
  ollama pull qwen3-vl:8b-instruct # ~8.8 GB (opcional, para OCR)
  ```

**Ventajas:**
- ✅ Sin costo de API
- ✅ Privacidad total (datos locales)
- ✅ Rápido (si GPU buena)
- ✅ Sin internet requerido para procesamiento

**Desventajas:**
- ❌ Inversión en hardware GPU
- ❌ Modelos ocupan 6-9 GB en disco

### ✅ Opción B: Backends Cloud — OpenAI, OpenRouter, Anthropic (Sin GPU)

**Requisitos:**
- API key del proveedor elegido, **en variable de entorno** (nunca en
  `.pdfsum-config.json`): `OPENAI_API_KEY` / `OPENROUTER_API_KEY` /
  `ANTHROPIC_API_KEY`.
- Conexión a internet.

**Configuración rápida:**
```bash
export PDFSUM_SUMMARIZER_BACKEND="openrouter"   # openai | openrouter | anthropic
export OPENROUTER_API_KEY="sk-or-..."
pdfsum doctor   # confirma backend + API key configurada
```

Default por proveedor — `openrouter` usa `qwen/qwen-2.5-7b-instruct` (el
**mismo** peso abierto que Ollama local, corriendo en la nube);
`openai`/`anthropic` no hostean Qwen, usan `gpt-4o-mini`/`claude-haiku-4-5`
por defecto. Cualquiera es overrideable con `--model`/`cloud_model`.

**Ventajas:**
- ✅ No requiere GPU
- ✅ Modelos de última generación (o los mismos pesos abiertos, vía OpenRouter)
- ✅ Sin mantenimiento de modelos

**Desventajas:**
- ❌ Costo por uso (más caro)
- ❌ Datos salen a internet
- ❌ Latencia de red

**👉 Ver `INSTALL.md` Sección 2 para configuración detallada**

---

## Instalación

### Opción A — Desde PyPI (usuarios, sin clonar el repo)

```bash
pip install pdfsum
pdfsum --help
pdfsum doctor
```

### Opción B — `uv` + repo local (desarrollo, recomendado para contribuir)

```bash
git clone https://github.com/idourra/pdf-summarizer.git && cd pdf-summarizer
uv sync                          # crea .venv + instala (determinista vía uv.lock)
uv run pdfsum doctor             # REQUIERE: Ollama corriendo O servicios remotos configurados
uv run pdfsum verify             # confirma resultados sobre la muestra incluida
```

> `uv` es la vía recomendada para desarrollo: instalación ~1-2s (vs 30-60s
> con pip) y reproducibilidad garantizada por `uv.lock`.

### Opción C — venv + pip desde repo local (legacy, más lento)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pdfsum doctor
pdfsum verify
```

### Opción D — Docker / Docker Compose (sin instalar Python/poppler/tesseract en el host)

**Más rápido** — wrapper que arma el `docker run` largo por ti:
```bash
bin/pdfsum-docker doctor
bin/pdfsum-docker run --in ./mis_pdfs --workspace ./data --lang por
```

O manual:
```bash
docker build -t pdfsum .
docker run --rm pdfsum pdfsum doctor

# Modo A (default, sin GPU passthrough): usa un Ollama ya corriendo en el host
cp .env.example .env && docker compose up --build

# Modo B (bundled, requiere GPU + NVIDIA Container Toolkit):
echo 'OLLAMA_HOST=http://ollama:11434' > .env
docker compose --profile gpu up --build

# Modo C (cloud puro, sin Ollama en absoluto):
printf 'PDFSUM_SUMMARIZER_BACKEND=openrouter\nOPENROUTER_API_KEY=sk-or-...\n' > .env
docker compose up --build
```

Los tres modos son configurables vía `.env` (`OLLAMA_HOST` o
`PDFSUM_SUMMARIZER_BACKEND`+API key) sin tocar
`compose.yml`; el servicio `ollama` embebido (con GPU) es opt-in detrás de
`--profile gpu`, nunca obligatorio. Detalle completo (incluye el fix de la
dependencia Pillow para el fallback de OCR por región) →
[`INSTALL.md` Sección 10](INSTALL.md#10-ejecutar-con-docker--docker-compose).

**⚠️ SI `pdfsum doctor` dice "XX ollama: no encontrado"**
→ Configura un backend cloud (env var + opcionalmente `.pdfsum-config.json`, Opción B arriba)

**Guía completa** (requisitos de sistema, modelos, troubleshooting):
→ [`INSTALL.md`](INSTALL.md) **Sección 2 (Modelos Local vs Remoto)**

## Uso

```bash
# FLUJO COMPLETO desde PDFs (la fuente): transcribe (OCR) + resume + report
# Requiere poppler + tesseract (OCR) y Ollama + qwen2.5:7b (resumen).
uv run pdfsum run --in ./pdfs --workspace ./data --lang por
#   -> ./data/ocr/<doc_id>.txt        (transcripciones cacheadas)
#   -> ./data/summaries/<doc_id>.json (resúmenes + _qa)
#   -> ./data/summaries/report.json   (métricas del lote)

# solo transcribir (PDF -> ocr/*.txt), sin resumir
uv run pdfsum transcribe --in ./pdfs --workspace ./data

# resumen de un texto ya transcrito (paso 2 aislado)
uv run pdfsum summarize --text transcripcion.txt --pages 4 --out resumen.json

# dry-run sin modelo (contrato + clasificación, para probar el flujo)
uv run pdfsum summarize --text transcripcion.txt --dry-run

# lote: directorio de .txt con cola idempotente + QA gates
uv run pdfsum batch --in ./_ocr_out --out ./_resumenes
# -> un .json por doc (con bloque _qa) + report.json (métricas del lote)

# export a registros LILACS (borrador para revisión humana)
uv run pdfsum export --in ./_resumenes --out lilacs.json

# registros bibliográficos BIBFRAME (JSON-LD), uno por documento/PDF
# (metadata embebida del PDF con precedencia si pasas --pdfs; borrador)
uv run pdfsum bibframe --in ./_resumenes --pdfs ./mis_pdfs --out ./_bibframe

# API de consulta local (solo lectura) sobre el lote
uv run pdfsum serve --batch-dir ./_resumenes --port 8765
# GET /api/summaries | /api/summaries/<doc_id> | /api/report
```

Salida: JSON con `doc_id`, `idioma_principal`, `tipo_documento`, `plantilla`,
`secciones`, `idiomas_resumo_origem`, `abstracts_origem`, `meta`.

## Versionado

Semantic Versioning (`MAJOR.MINOR.PATCH`):

| Cambio | Ejemplo |
|---|---|
| `MAJOR` | Cambio incompatible en el contrato JSON de salida |
| `MINOR` | Nueva fase/capacidad compatible (p. ej. 0.9 → 0.10 = resumen jerárquico) |
| `PATCH` | Correcciones sin cambio de contrato (p. ej. 0.11.0 → 0.11.1 = fix dependencia dev) |

Historial completo en [`CHANGELOG.md`](CHANGELOG.md). Cada versión integrada
se marca con `git tag -a vX.Y.Z`.

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
- **Fase 10 (resumen jerárquico por capítulos):** ✅ completada — 12/12
  criterios (`evals/eval-spec-fase10-resumen-jerarquico-capitulos.yaml`).
  Estrategia `--long-strategy hierarchical` para libros/documentos largos
  (detección de capítulos + resumen y consolidación por capítulo).
- **Fase 11 (migración a uv):** ✅ completada (`evals/eval-spec-fase11-migracion-uv.yaml`).
  Gestor de dependencias moderno, `uv.lock` para reproducibilidad.
- **Fase 12 (distribución moderna):** ✅ completada
  (`evals/eval-spec-fase12-distribucion-moderna-uv.yaml`). Backend `hatchling`,
  `uv build` genera wheel/sdist, publicación en PyPI (`pip install pdfsum`).
- Ver `docs/ESTADO.md` y `docs/PROPUESTA-PRODUCTO.md`.
