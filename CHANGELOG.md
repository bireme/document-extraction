# Changelog — pdfsum

Formato basado en [Keep a Changelog](https://keepachangelog.com/); versionado
semántico. Repositorio en GitHub (`idourra/pdf-summarizer`): flujo
rama → PR → CI → merge; las versiones se marcan con tags `vX.Y.Z`
(el tag dispara la publicación a PyPI vía `publish.yml`).

## [Unreleased]
### Corregido
- Estrategia `hierarchical`: `_summarize_chapter()` llamaba dos veces a
  `summarize_in_blocks()` con argumentos idénticos, duplicando TODAS las
  llamadas al LLM de cada capítulo largo (coste y latencia x2, mismo
  resultado). Ahora una sola pasada (N bloques + 1 consolidación).
  Spec: `evals/eval-spec-lite-fix-hierarchical-doble-resumen.yaml`
  (issue #12).

## [0.13.0] — 2026-09-01 — Observabilidad durable, backends cloud, BIBFRAME y Docker

> Consolida seis entregas mergeadas desde v0.12.0 (PRs #1–#6, #8–#9).
> **Breaking change**: `batch` y `run` devuelven `rc=1` si hay fallos de
> procesamiento (ver «Observabilidad durable → Cambiado»).

### Observabilidad durable (PR #6/#9)
#### Añadido
- Observabilidad durable para `run` y `batch`: `events.jsonl` sincronizado por
  evento, `infrastructure.jsonl` con muestras periódicas de CPU, RAM, swap,
  disco, temperatura y GPU cuando están disponibles, y resumen de picos/mínimos
  en `report.json`.
- `report.json` versión 3.0 se escribe atómicamente al inicio y después de cada
  documento, con `run_id`, estado y progreso. Las fallas quedan asociadas al
  documento y no interrumpen el resto del lote; una interrupción preserva el
  último checkpoint confirmado.
- Observación de aceleradores ampliada: `/api/ps` registra modelos activos y
  VRAM asignada por Ollama remoto; `nvidia-smi` añade métricas por GPU de uso,
  memoria, temperatura, potencia, ventilador, clocks y throttling. El override
  `compose.gpu-observability.yml` expone esas métricas físicas a `pdfsum` de
  forma opt-in sin volver obligatoria una GPU NVIDIA.
#### Cambiado
- **Breaking change para scripts:** los comandos `batch` y `run` ahora
  devuelven código de salida `1` (`rc=1`) cuando se producen fallos de
  procesamiento en uno o más documentos. Las automatizaciones que dependan
  del código de salida deben contemplar este nuevo comportamiento.

### Fix publicación PyPI por tag
#### Corregido
- `publish.yml`: retirado `cache: "uv"` de `actions/setup-python@v5` (no
  soportado; el job `build` moría en "Set up Python" y **la publicación de
  v0.12.0 a PyPI nunca ocurrió**). Mismo bug que `FIX-CI-UV-CACHE-INFRA`
  corrigió en `ci.yml`; criterio C1 ampliado a ambos workflows.

### Selección del modelo VLM para OCR (PR #8)
#### Añadido
- Flag `--vlm-model` en `run` y `transcribe` (más `resolve_vlm_model()`:
  flag > config `vlm_model` > default del backend) para elegir qué modelo
  de visión usa el fallback VLM de OCR sin tocar código.

### Registros bibliográficos BIBFRAME (FASE15)
#### Añadido
- **Extracción de datos bibliográficos** de los documentos procesados:
  nuevo adaptador `adapters/pdf_metadata.py` (metadata embebida del PDF
  vía `pdfinfo`: Title, Subject/capítulo, Author, Keywords, CreationDate,
  Pages; tolerante a fallos) + módulo de DOMINIO `bibframe.py` que
  combina esa metadata (precedencia, es explícita) con el resumen ya
  generado (título, entidad, términos candidatos, idioma, páginas) y
  registra la fuente de cada campo.
- **Registro BIBFRAME 2.x en JSON-LD por cada PDF/documento**: nuevo
  subcomando `pdfsum bibframe --in <summaries> [--pdfs <dir>] --out
  <dir>` — emite `<doc_id>.bibframe.json` (par bf:Work + bf:Instance
  enlazados por bf:instanceOf, vocabulario id.loc.gov) cuando hay dato
  mínimo (título), y `bibframe_report.json` con generados/omitidos y
  motivo. Idioma mapeado a códigos LOC (es->spa, pt->por, en->eng).
  Registros marcados `draft` para revisión humana (mismo criterio que el
  export LILACS), con bloque `_pdfsum.sources` de trazabilidad.
- `Workspace.bibframe_dir`/`bibframe_path()`; documentado en README.md y
  GUIA-USO.md.
#### Verificado
- 21 tests nuevos (154 total): dominio (precedencia/dato mínimo/JSON-LD),
  adaptador (subprocess mockeado), CLI (un registro por doc, omitidos
  con motivo, --pdfs opcional). Arquitectura AST: bibframe.py en
  DOMAIN_MODULES, sin imports de adaptadores.
- E2E real: 15/15 registros generados sobre el lote ECIMED procesado,
  con metadata real de los PDFs (título del libro, autor, año, capítulo)
  + materias/idioma del resumen. Spec: `evals/eval-spec-fase15-bibframe.yaml`.

### bin/pdfsum-docker: wrapper CLI para Docker
#### Añadido
- `bin/pdfsum-docker`: wrapper bash que arma el `docker run --network
  host` largo (3 volúmenes fijos del repo + `-w /work` para rutas
  relativas a tu `$PWD` de invocación) y reenvía argumentos a `pdfsum`.
  Funciona desde cualquier directorio; construye la imagen si falta
  (`--build` fuerza rebuild). Documentado en `.gitignore`
  (`_docker_smoke/`), `README.md` y `INSTALL.md` §10 como vía
  recomendada, junto con una nota sobre por qué `--network host` hace
  falta (Ollama suele escuchar solo en `127.0.0.1`, no en
  `host.docker.internal`).
#### Verificado
- `bin/pdfsum-docker doctor` invocado desde `/tmp` (cwd distinto al
  repo): reporta resumen y OCR VLM listos con el Ollama nativo del host.
- `bin/pdfsum-docker run --in ./samples/pdfs --workspace
  ./_docker_smoke --lang por`: 2/2 PDFs OK, resumen real (no fake).
- Spec: `evals/eval-spec-lite-docker-cli-wrapper.yaml`.

### Backends de inferencia en la nube configurables (FASE14)
#### Añadido
- **Backends cloud reales para el Summarizer** (antes solo prometidos en
  docs, nunca implementados): `adapters/cloud_summarizer.py`
  (`CloudSummarizer`, API Chat Completions estilo OpenAI — sirve para
  `openai`, `openrouter` y cualquier gateway compatible vía `base_url`) y
  `adapters/anthropic_summarizer.py` (`AnthropicSummarizer`, API Messages
  nativa de Anthropic). Sin SDKs nuevos: `urllib`, mismo patrón que
  `ollama_summarizer.py`.
- `adapters/llm_prompt.py`: instrucciones por idioma + parseo de secciones
  Markdown extraídos de `ollama_summarizer.py` a un módulo agnóstico de
  transporte, reusado por los 3 adaptadores (sin duplicación).
- `adapters/summarizer_factory.py`: resuelve backend (flag CLI > env
  `PDFSUM_SUMMARIZER_BACKEND` > `.pdfsum-config.json` `summarizer_backend`
  > default `ollama`) y modelo (flag > config `model`/`cloud_model` >
  default por backend). Default real "mismos modelos en la nube": el
  backend `openrouter` usa `qwen/qwen-2.5-7b-instruct` (mismo peso abierto
  que `qwen2.5:7b` local, hosteado). `openai`/`anthropic` no hostean Qwen
  → default propio del proveedor (`gpt-4o-mini` / `claude-haiku-4-5`).
  Cualquier modelo es configurable (`--model`/`cloud_model`).
- CLI: flag `--backend {ollama,openai,openrouter,anthropic}` en
  `summarize`, `batch`, `run`, `verify`, `doctor`.
- `doctor.py` backend-aware: si el backend es cloud, chequea presencia de
  la API key (env var) en vez de Ollama+modelo, sin llamada de red; Ollama
  se sigue reportando aparte (informativo, solo para el fallback VLM de
  OCR de escaneos difíciles, independiente del backend de resumen).
- `compose.yml`: pasa `PDFSUM_SUMMARIZER_BACKEND`, `OPENAI_API_KEY`,
  `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` al contenedor `pdfsum` vía
  `${VAR:-}` (nunca hardcodeadas); nuevo "Modo C" (cloud puro, sin Ollama)
  documentado en `.env.example`/`INSTALL.md` §10.
#### Corregido
- README.md/INSTALL.md §2 ("Opción B: Modelos Remotos"): la versión
  anterior rometía `summarizer_backend`/`openai_api_key` en
  `.pdfsum-config.json` que el código **nunca implementó** (`cli.py` solo
  construía `OllamaSummarizer`/`FakeSummarizer`). Reescrita para reflejar
  el mecanismo real (esta fase) y corregidas dos referencias cruzadas a
  secciones incorrectas, preexistentes.
#### Seguridad
- Ninguna API key se lee de `.pdfsum-config.json` ni se imprime en
  mensajes de error — solo variables de entorno (`OPENAI_API_KEY` /
  `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY`), verificado con test dedicado.
#### Verificado
- `make check`: 133/133 tests (97 previos + 36 nuevos), lint limpio; 0
  llamadas de red reales en tests (urlopen mockeado).
- Docker real: `docker run -e PDFSUM_SUMMARIZER_BACKEND=openai -e
  OPENAI_API_KEY=test pdfsum pdfsum doctor` → backend detectado, key
  confirmada, capacidad "resumen" en SÍ sin Ollama.
- Detalle completo: `evals/eval-spec-fase14-backends-cloud.yaml`.

### Fix runtime Pillow + Ollama configurable en Docker (FASE13)
#### Corregido
- **Pillow ahora dependencia real de runtime** (`pyproject.toml`:
  `dependencies = ["pillow>=10"]`, antes solo en `[dependency-groups].dev`).
  Corrige el `ModuleNotFoundError: No module named 'PIL'` documentado abajo
  (entrada anterior) para el fallback de OCR por región dentro de Docker.
  `uv.lock` regenerado.
- Lint preexistente (orden de imports en `adapters/doctor.py` y
  `adapters/ollama_summarizer.py`, deuda no relacionada que bloqueaba
  `make check`): normalizado con `ruff check --fix` (cambio puramente
  cosmético, sin cambio de comportamiento).
#### Cambiado
- `compose.yml`: el servicio `ollama` (con `gpus: all`) ahora vive detrás de
  `profiles: ["gpu"]` (opt-in, no arranca con `docker compose up` por
  defecto). El servicio `pdfsum` ya no tiene `depends_on: ollama` forzoso;
  `OLLAMA_HOST` es configurable vía `${OLLAMA_HOST:-http://host.docker.internal:11434}`
  con `extra_hosts: host-gateway` para que resuelva también en Linux.
- Nuevo `.env.example` documentando ambos modos (Ollama del host — default,
  sin GPU passthrough — vs. Ollama embebido con `--profile gpu`).
- `.github/workflows/ci.yml`: nuevo job `docker` (build de imagen + smoke
  test de `doctor`/`transcribe` sobre la muestra que ejercita el fallback
  Pillow + validación de `compose.yml` en ambos perfiles) para que esta
  regresión no vuelva a pasar inadvertida.
- `README.md` / `INSTALL.md` §10: reescritos con los dos modos de uso de
  Ollama con Docker; retirada la limitación conocida (ya resuelta).
#### Verificado
- `make check`: 97/97 tests, lint limpio.
- `docker build` + `docker run ... pdfsum transcribe` sobre
  `samples/pdfs/56186_10006001927.pdf` (el PDF que antes fallaba): OK, sin
  traceback.
- `docker compose config` y `docker compose --profile gpu config`: ambos
  manifiestos válidos.
- Detalle completo y criterios: `evals/eval-spec-fase13-docker-ollama-runtime.yaml`.

### Soporte Docker / Docker Compose
#### Añadido
- `Dockerfile` (`python:3.12-slim` + `poppler-utils` + `tesseract-ocr` con
  idiomas `por`/`eng`/`spa` + `curl`; `pip install .` del paquete; `CMD
  ["pdfsum", "--help"]`). PR #1 (`bireme/master`, mergeado 2026-08-26).
- `compose.yml`: servicio `pdfsum` (build local) + servicio `ollama`
  (`ollama/ollama:0.33.0`, con `gpus: all` y volumen nombrado
  `ollama_models`), volúmenes `./input:/input:ro`, `./output:/output`,
  `./logs:/logs`, `OLLAMA_HOST=http://ollama:11434` inyectado al servicio
  `pdfsum`.
- `.dockerignore` (excluye `.git`, `.venv`, `__pycache__`, PDFs de prueba,
  `data/`, `data_hierarchical/`) y carpetas `input/`, `output/`, `logs/`
  (con `.gitkeep`) como puntos de montaje.
#### Verificado (2026-08-26, manual, ver `INSTALL.md` §10)
- `docker build -t pdfsum .`: build limpio OK (paquete `pdfsum` instalado vía
  `pip install .` dentro de la imagen).
- `docker run --rm pdfsum` (CMD por defecto) y `pdfsum doctor` dentro del
  contenedor: OK — reporta correctamente poppler/tesseract disponibles y
  Ollama no alcanzable (esperado sin el servicio `ollama` arriba).
- `docker compose config`: manifiesto válido, sin errores de sintaxis.
- `pdfsum transcribe` dentro del contenedor sobre `samples/pdfs/`: **1 de 2
  PDFs de muestra falla** con `ModuleNotFoundError: No module named 'PIL'`
  en `adapters/hybrid_ocr.py:_ocr_regions` (ruta de OCR por región cuando el
  VLM no está disponible y degrada a Tesseract con recorte de regiones).
#### Conocido — limitación encontrada en esta verificación
> ✅ **Resuelta** en la entrada `[Unreleased] — Fix runtime Pillow + Ollama
> configurable en Docker (FASE13)` de arriba.
- **Causa raíz**: `pyproject.toml` declara `dependencies = []` (núcleo solo
  stdlib) y `Pillow` solo en `[dependency-groups].dev` (añadido en 0.11.1
  para que los *tests* no fallaran). La imagen Docker instala con
  `pip install .` (sin grupos `dev`), así que `Pillow` **no** está presente
  en runtime — pero `hybrid_ocr.py` sí lo importa en producción para el
  fallback de OCR por región. Fuera de Docker esto queda enmascarado porque
  `uv sync` (entorno de desarrollo) instala el grupo `dev` por defecto.
- **Impacto**: `pdfsum run` / `pdfsum transcribe` sobre PDFs escaneados que
  activan el fallback por región (típicamente cuando el VLM
  `qwen3-vl:8b-instruct` no está disponible) fallan con traceback dentro del
  contenedor. No afecta PDFs con texto nativo ni todos los escaneados (1 de
  los 2 PDFs de muestra funcionó sin problema).
- **Recomendación**: seguir el flujo EDD (spec antes de código) para abrir
  `fix/OS-NNN` que mueva `pillow` de `dev` a `dependencies` en
  `pyproject.toml` — es una dependencia de runtime real, no solo de tests.
- **Alternativa de infraestructura sin fix de código**: si el host no tiene
  `nvidia-container-toolkit` (caso de esta verificación), el servicio
  `ollama` de `compose.yml` (`gpus: all`) no arrancará; usar en su lugar un
  Ollama nativo del host y apuntar el contenedor `pdfsum` vía
  `OLLAMA_HOST=http://host.docker.internal:11434` (ver `INSTALL.md` §10).

## [0.12.0] — 2026-08-25 — Distribución moderna: hatchling + uv build + PyPI
### Añadido
- Backend de build moderno: `setuptools` → `hatchling` en `pyproject.toml`.
- `uv build` genera wheel (`.whl`) + sdist (`.tar.gz`) reproducibles;
  `[tool.hatch.build.targets.sdist].exclude` evita empaquetar `samples/pdfs`,
  `data_hierarchical`, `data/ocr`, `entregable` (127 KB sdist vs 3.3 MB antes).
- Metadata PyPI completo: `classifiers`, `project.urls` (Homepage, Repository,
  Issues, Changelog).
- `.github/workflows/publish.yml`: publica automáticamente a Test PyPI y luego
  PyPI production al crear un tag `vX.Y.Z` (gate: suite de tests completa
  antes de publicar; requiere secrets `TEST_PYPI_API_TOKEN` / `PYPI_API_TOKEN`).
- `.github/workflows/ci.yml`: nuevo job `build` (`uv build` + smoke test del
  wheel en venv limpio) en cada push/PR.
- `INSTALL.md` / `README.md`: 3 vías de instalación documentadas
  (PyPI / `uv` + repo local / venv+pip legacy) y sección de versionado
  semántico.
### Corregido
- `ruff format --check`: 67 archivos con formato desactualizado (deuda
  preexistente, no relacionada con esta fase) — normalizados con
  `ruff format`, cambios puramente cosméticos (sin cambio de comportamiento).
### Verificado
- 97/97 tests OK en entorno limpio (`rm -rf .venv && uv sync`).
- `ruff check` y `ruff format --check`: sin issues.
- Wheel instalado en venv limpio: `pdfsum --help` y `pdfsum doctor` OK.
- eval-spec `FASE12`: 10/10 criterios.

## [0.11.1] — 2026-08-25 — Fix: Pillow como dependencia dev declarada
### Corregido
- **Regresión de la migración a uv (0.11.0)**: `Pillow` nunca estuvo declarado
  en `pyproject.toml`; en un `uv sync` limpio (entorno aislado, sin paquetes
  globales) los tests `test_segment.py`, `test_hybrid_ocr.py` y
  `test_hybrid_seg.py` fallaban con `ModuleNotFoundError: No module named
  'PIL'` (3 módulos completos sin cargar → 89/97 tests reales ejecutados,
  no 97/97 como afirmaba el registro de 0.11.0).
- Causa raíz: la verificación de 0.11.0 se corrió sobre un entorno que ya
  tenía Pillow instalado globalmente (fuera de uv), lo que ocultó la falta
  de declaración explícita.
- Fix: nuevo `[dependency-groups] dev = ["pillow>=10"]` en `pyproject.toml`
  (Pillow solo se usa para generar imágenes sintéticas en tests, nunca en
  `src/`). `uv sync` instala grupos dev por defecto — sin cambios en el
  flujo de instalación para el usuario.
### Verificado
- `rm -rf .venv && uv sync && uv run python -m unittest discover tests`:
  **97/97 tests OK** en entorno completamente limpio.
- `uv run ruff check .`: sin issues.

## [0.11.0] — 2026-08-25 — Migración a uv (gestor moderno Python)
### Cambiado
- **Flujo de instalación**: `uv sync` es primario (10x más rápido, ~1-2s);
  `venv + pip` es fallback legacy.
- `uv.lock` generado (determinismo, reproducibilidad garantizada).
- INSTALL.md reescrito: pasos más simples con `uv run <cmd>`
  (sin "source .venv/bin/activate").
### Beneficios
- Resolución de deps robusta (backtracking inteligente).
- ~1-2s instalación vs ~30-60s con pip.
- UX mejorada (output claro, mejor rendimiento).
### Verificado
- 97 tests OK (sin regresión).
- `uv run pdfsum verify`: PASS.

## [0.10.0] — 2026-08-24 — Resumen jerárquico por capítulos (coexistencia de estrategias)
### Añadido
- `chapters.py` (dominio puro): detección de capítulos por regex con fallback a
  bloques si no hay estructura.
- `consolidation.py` (dominio puro): deduplicación inteligente de campos
  repetibles (publico, terminos) en consolidaciones finales.
- `config.py`: lectura de `.pdfsum-config.json` (local o `~/.pdfsum-config.json`)
  para personalizar defaults sin tocar CLI.
- `long_strategy="hierarchical"`: nueva estrategia con cobertura 100%, tiempo ~600s
  para libro 1M+ chars, calidad óptima (coherencia capitular).
- Tabla de trade-offs en GUIA-USO.md: excerpt (3%, 15s), blocks (100%, 60s),
  hierarchical (100%, 600s).
### Importante
- **Estrategias coexisten, no se sustituye una por otra.** Default sigue siendo
  `excerpt` (backward compatible).
### Verificado
- eval-spec `FASE10`: 12 criterios; 97 tests (sin regresión); ruff limpio.
- End-to-end con `crisis_familianuevo` (362 pág, 1M chars): meta correcto,
  no hay repeticiones, QA ok.

## [0.9.0] — 2026-08-20 — Segmentación de página (columnas/bloques)
### Añadido
- `segment.py` (dominio): detección de columnas (proyección vertical + canal
  ancho) y bloques (proyección horizontal), con orden de lectura y filtrado de
  márgenes sin contenido. Solo Pillow, sin cv2.
- `hybrid_ocr.py`: segmenta cada página en regiones, hace OCR por región y
  ensambla el texto en orden de lectura (cierra la lección del primer análisis:
  página entera al VLM falla; hay que segmentar).
### Corregido
- Gate de idioma QA: no marca error entre idiomas cercanos (pt/es), que el
  detector por stopwords confunde (falso positivo en resúmenes bilingües).
### Verificado
- eval-spec `FASE8-SEGMENTACION`: 8/8 criterios; 82 tests; ruff limpio.
- End-to-end lote mixto: 15/15 tokens del difícil 57128, ambos QA ok.

## [0.8.0] — 2026-08-19 — Paridad OCR con el piloto (fallback VLM)
### Añadido
- `ocr_routing.py` (dominio): decisión por página Tesseract vs VLM según
  confianza/palabras de Tesseract (replica del piloto).
- Puerto `PageOCR` + adaptador `VlmPageOCR` (Ollama vision, prompt+ruta en una
  sola cadena — lección del piloto que evita el hang/meta-razonamiento).
- `adapters/hybrid_ocr.py`: transcriptor nativo + Tesseract con fallback VLM;
  es el transcriptor por defecto del CLI.
- Sin VLM disponible, degrada a Tesseract con aviso (siguiera funcional).
### Verificado
- eval-spec `FASE7-OCR-VLM`: 8/8 criterios; 76 tests; ruff limpio.
- Paridad con el piloto sobre 57128 (difícil): VLM en las 3 páginas, cobertura
  1.00 del abstract (igualdad completa).

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
