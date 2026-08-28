# Instalación y reproducibilidad — pdfsum

Guía para que **otra persona con una GPU similar o superior** instale la
aplicación, la ejecute y **verifique que obtiene resultados similares**.

> ⚠️ **Reproducibilidad ≠ salida idéntica.** El resumen lo genera un LLM local,
> que **no es determinista** (aun a temperatura baja): el texto variará entre
> ejecuciones y máquinas. Por eso la verificación **no** compara byte a byte,
> sino que comprueba, sobre una muestra incluida, que se cumplen criterios
> objetivos: idioma correcto, tipo correcto y **cobertura de términos clave**
> por encima de un umbral (ver `pdfsum verify`).

---

## 1. Requisitos

### Precondiciones por capacidad (qué necesitas según lo que quieras hacer)

| Quiero... | Necesito (además de Python ≥ 3.10) |
|---|---|
| Leer PDFs con texto nativo | **poppler-utils** |
| Transcribir PDFs **escaneados** | poppler + **Tesseract** (+ idioma, p. ej. `por`) |
| **Generar resúmenes** (núcleo) | **Ollama en ejecución** + modelo **`qwen2.5:7b`** descargado |
| OCR de escaneos difíciles | Ollama + modelo **`qwen3-vl:8b-instruct`** |

> **Sí: para resumir, Ollama debe estar instalado, en ejecución y con el modelo
> descargado.** No es opcional — es la precondición del núcleo. Si falta, los
> comandos que resumen (`run`, `batch`, `summarize`, `verify`) se detienen con
> un mensaje claro (no una traza) indicando qué instalar. Comprueba tu entorno
> en cualquier momento con **`pdfsum doctor`** (muestra checks + capacidades).

### Hardware (referencia del pilotaje)

**OPCIÓN A: Local con GPU (recomendado)**
- GPU con **≥ 8 GB VRAM** (probado en RTX 5060 Laptop, 8 GB) + ~16 GB RAM
- Todos los modelos corren localmente sin costo de API
- Con GPU superior, más rápido aún

**OPCIÓN B: Sin GPU local (o GPU < 8 GB)**
- Configura acceso a un backend cloud (OpenAI, OpenRouter o Anthropic)
- Requiere API key de proveedor externo (env var) + plan pagado
- Ver Sección 2 (Configuración de Modelos — Opción B: Backends Cloud)
- Ideal si no tienes GPU; OpenRouter permite usar los mismos pesos abiertos
  (Qwen) que el modo local, solo que hosteados en la nube

### Software de sistema
- **Python ≥ 3.10**
- **poppler-utils** (`pdftotext`, `pdfinfo`, `pdftoppm`) — requisito duro.
- **Tesseract OCR** + idiomas del corpus. El default de `pdfsum` es el
  combo `por+eng+spa` (Tesseract combina diccionarios en una sola pasada);
  instala los tres paquetes de idioma como mínimo. Para más idiomas en el
  corpus (p. ej. francés), instala el paquete y añade el código a `--lang`
  (ej. `--lang por+eng+spa+fra`).
- **Ollama** (runtime de modelos locales) + los modelos [**SOLO si tienes GPU ≥ 8 GB**]
  - `qwen2.5:7b` — generación de resúmenes (texto, 6.3 GB VRAM)
  - `qwen3-vl:8b-instruct` — OCR de escaneos difíciles (visión, opcional)
  - **CRÍTICO**: Sin Ollama + modelos descargados, los comandos de resumen fallarán

```bash
# Debian/Ubuntu (requiere GPU ≥ 8 GB)
sudo apt install python3 python3-venv poppler-utils \
     tesseract-ocr tesseract-ocr-por tesseract-ocr-spa tesseract-ocr-eng

# Ollama DEBE estar instalado Y ejecutándose
# Ver: https://ollama.com

# Descargar los modelos (requiere ~6-9 GB de disco + espacio en GPU)
ollama pull qwen2.5:7b          # ~6.3 GB
ollama pull qwen3-vl:8b-instruct # ~8.8 GB (opcional, para OCR avanzado)

# Iniciar Ollama (en otra terminal, déjalo corriendo)
ollama serve
```

---

## 2. Configuración de Modelos (Local vs. Remoto)

### 🔴 REQUISITO CRÍTICO: Configurar Summarizer

Antes de usar `pdfsum`, **DEBE** haber un Summarizer configurado:

#### ✅ Opción A: Modelos Locales (Ollama) — RECOMENDADO

**Requiere:**
- GPU con ≥ 8 GB VRAM (probado en RTX 5060 Laptop)
- Ollama instalado y ejecutándose (`ollama serve`)
- Modelos descargados (`ollama pull qwen2.5:7b`)
- Sin costos de API, máxima privacidad, máxima velocidad (si GPU es buena)

```bash
# Verificar que Ollama está corriendo
curl http://localhost:11434/api/tags
# Debe retornar JSON con lista de modelos

# Si no está corriendo, iniciar en otra terminal:
ollama serve
```

**Ventajas:**
- ✅ Sin costo de API
- ✅ Datos NO salen de tu máquina (privacidad total)
- ✅ Rápido (si GPU es decente)
- ✅ Sin dependencia de internet para procesamiento

**Desventajas:**
- ❌ Requiere GPU ≥ 8 GB (inversión inicial)
- ❌ Modelos ocupan 6-9 GB en disco

#### ✅ Opción B: Backends Cloud (OpenAI, OpenRouter, Anthropic) — FASE14

Implementado de verdad (`adapters/cloud_summarizer.py`,
`adapters/anthropic_summarizer.py`, `adapters/summarizer_factory.py`) —
cualquier proveedor de inferencia con API HTTP: OpenAI, OpenRouter (mismos
pesos abiertos que usamos local, p. ej. Qwen, pero hosteados) o Anthropic.
Sin SDKs adicionales (solo `urllib`, igual que el adaptador Ollama).

**Requiere:**
- API key del proveedor elegido, en **variable de entorno** (nunca en
  `.pdfsum-config.json` — evita comitear secretos):
  `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY`.
- Conexión a internet. Sin GPU local necesaria para resumir (el fallback
  VLM de OCR de escaneos difíciles sigue siendo exclusivamente Ollama,
  independiente de este backend — si no hay Ollama, degrada a Tesseract).

**Configuración (elige backend + modelo, la key va SOLO en env):**
```bash
# Backend + modelo: env var (prevalece) o .pdfsum-config.json
export PDFSUM_SUMMARIZER_BACKEND="openrouter"   # openai | openrouter | anthropic
export OPENROUTER_API_KEY="sk-or-..."

pdfsum doctor      # confirma que la API key está configurada (sin llamar a la red)
pdfsum run --in ./pdfs --workspace ./data --lang por
# --backend/--model como flags CLI también sobreescriben (prevalecen sobre env/config)
pdfsum run --in ./pdfs --workspace ./data --backend anthropic --model claude-haiku-4-5
```

O en `.pdfsum-config.json` (sin secretos, solo backend/modelo por defecto):
```json
{
  "summarizer_backend": "openrouter",
  "cloud_model": "qwen/qwen-2.5-7b-instruct"
}
```

**"Los mismos modelos que tenemos, corriendo en la nube"**: solo
**OpenRouter** hostea de verdad el peso abierto que usamos local
(`qwen/qwen-2.5-7b-instruct` = mismo Qwen que `qwen2.5:7b` en Ollama, en su
nube). OpenAI/Anthropic no hostean Qwen — sus defaults son un modelo propio
razonable del proveedor. **Configurar cualquier otro LLM**: cambia
`cloud_model` (o `--model`) por cualquier id soportado por ese proveedor,
sin tocar código.

| Backend | Env var de API key | Modelo por defecto | Nota |
|---|---|---|---|
| `openrouter` | `OPENROUTER_API_KEY` | `qwen/qwen-2.5-7b-instruct` | mismo peso abierto que Ollama local, en la nube |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` | API Chat Completions estándar |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-haiku-4-5` | API Messages nativa (no Chat Completions) |

**Ventajas:** sin GPU requerida; escalable; acceso a modelos de última
generación. **Desventajas:** costo por uso; datos salen a servidores
externos; dependencia de internet/latencia de red.

#### 🤔 ¿Cuál elegir?

| Escenario | Recomendación |
|---|---|
| Tengo GPU ≥ 8 GB | **Ollama local** (mejor relación costo/beneficio) |
| No tengo GPU, quiero los mismos pesos abiertos | **OpenRouter** (Qwen hosteado) |
| Procesamiento ocasional / máxima calidad | **OpenAI/Anthropic** (modelos propietarios) |
| Procesamiento masivo | **Ollama local** (sin costos recurrentes) |
| Privacidad crítica | **Ollama local** (datos en casa) |

Detalle técnico completo y criterios:
`evals/eval-spec-fase14-backends-cloud.yaml`.

---

## 3. Instalación de la aplicación

**IMPORTANTE**: Antes de instalar, asegúrate de haber elegido tu estrategia
de Summarizer en la Sección 2 (Ollama local o servicios remotos).

El núcleo Python no tiene dependencias externas (solo stdlib): se instala directo.
Tres opciones, ordenadas por recomendación:

### Opción A: `uv` + repo local (desarrollo — recomendado para contribuir)

[Instala `uv`](https://docs.astral.sh/uv/getting-started/) si aún no lo tienes.

```bash
git clone https://github.com/idourra/pdf-summarizer.git && cd pdf-summarizer
uv sync                   # crea .venv + instala pdfsum (determinístico en uv.lock)
uv run pdfsum --help      # sin 'source .venv/bin/activate'
```

Los comandos `pdfsum` se invocan así:
- `uv run pdfsum run --in ./pdfs --workspace ./data`
- `uv run pdfsum doctor`
- `uv run pdfsum verify`

> **Ventaja**: uv.lock garantiza reproducibilidad; instalación ~1-2s (vs. 30s+ con pip).
> Es la vía recomendada si vas a modificar el código (ver `CONTRIBUTING.md`).

### Opción B: `pip install pdfsum` (desde PyPI — recomendado para usuarios)

Si solo quieres **usar** `pdfsum` (sin clonar el repo ni tocar código):

```bash
pip install pdfsum
pdfsum --help
pdfsum doctor
pdfsum verify
```

> **Nota**: requiere que el paquete esté publicado en PyPI (ver "Distribución
> moderna" más abajo). Si aún no está publicado, usa la Opción A o instala
> el wheel generado localmente: `uv build && pip install dist/pdfsum-*.whl`.

### Opción C: venv + pip desde repo local (legacy, no recomendado)

Solo si no puedes usar `uv` ni PyPI (entorno restringido):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pdfsum --help
```

> **Nota**: `pip` es más lento (~30-60s en 1ra instalación); no hay uv.lock
> para reproducibilidad garantizada. Preferir Opción A o B.

---

## 4. Verificar la Instalación

### Con `uv`:
```bash
uv run pdfsum doctor
```

### Con venv:
```bash
source .venv/bin/activate && pdfsum doctor
```
Lista cada dependencia como `[duro]` u `[opc]` y dice si el **entorno mínimo**
está listo:

**Salida típica:**
```
Verificación de entorno pdfsum:
  OK [duro]  pdftotext: encontrado
  OK [duro]  pdfinfo: encontrado
  OK [duro]  pdftoppm: encontrado
  OK [opc]   tesseract: encontrado
  OK [opc]   tesseract-por: instalado
  OK [duro]  ollama: corriendo (en localhost:11434)
  OK [duro]  model:qwen2.5:7b: descargado y disponible
  ⚠️ [opc]   model:qwen3-vl:8b-instruct: NO (OCR avanzado solo)
```

**Qué significa cada línea:**
- `OK [duro]`: Obligatorio. Sin esto, pdfsum no funciona.
- `OK [opc]`: Opcional. Funcionalidad limitada sin esto (ej: sin tesseract → no OCR)
- `⚠️ [opc]`: Opcional pero ausente (no crtico, pero nice-to-have)
- `XX [duro]`: ERROR CRÍTICO. Debes configurar esto antes de continuar.

**Caso especial: Ollama**
- Si ves `XX ollama: no encontrado` → configura un backend cloud (Sección 2, Opción B) o instala/arranca Ollama
- Si ves `OK ollama: corriendo` pero `XX model:qwen2.5:7b` → descargar: `ollama pull qwen2.5:7b`

---

## 5. Verificar que obtiene resultados similares

La aplicación incluye una **muestra** (`samples/pdfs/`) y un **set de control**
(`samples/control_set.json`) con expectativas verificables.

### Con `uv`:
```bash
uv run pdfsum verify --workspace ./_verify --lang por+eng+spa
```

### Con venv:
```bash
source .venv/bin/activate && pdfsum verify --workspace ./_verify --lang por+eng+spa
```
Corre el flujo completo (transcribe → resume) sobre la muestra y evalúa contra
el set de control. Imprime:

```
Aceptación: PASS
  cobertura media 0.75 (umbral 0.60: ok); idioma ok; tipo ok
  - 58739_deixar_fumar: cobertura 1.0 lang=ok tipo=ok
  - 56186_10006001927: cobertura 1.0 lang=ok tipo=ok
```
- **PASS** (código de salida 0) = resultados similares a la referencia.
- **FAIL** (código 1) = revisar entorno/modelos (ver §3) o el umbral.
- Ajustable: `--min-coverage 0.6`, `--model`, `--long-strategy blocks`.
- `pdfsum verify --fake` prueba el **arnés** sin modelos (útil para CI).

---

## 6. Uso real sobre tus propios PDFs

```bash
# flujo completo desde una carpeta de PDFs (la fuente)
pdfsum run --in ./mis_pdfs --workspace ./data --lang por
#   ./data/ocr/<doc>.txt         transcripciones (cacheadas)
#   ./data/summaries/<doc>.json  resúmenes + control de calidad (_qa)
#   ./data/summaries/report.json métricas del lote

# export a registros de catalogación LILACS (borrador para revisión)
pdfsum export --in ./data/summaries --out ./data/lilacs.json

# API de consulta local (solo lectura)
pdfsum serve --batch-dir ./data/summaries --port 8765
```

---

## 7. Distribución moderna: build + publicación en PyPI

El proyecto usa `hatchling` como build backend (`pyproject.toml`), compatible
con `uv build` para generar artefactos reproducibles.

### Generar wheel + sdist

```bash
uv build
ls -lh dist/
# pdfsum-X.Y.Z-py3-none-any.whl  (wheel binario)
# pdfsum-X.Y.Z.tar.gz            (source distribution)
```

### Verificar el wheel en un entorno limpio

```bash
python3 -m venv /tmp/pdfsum-check
/tmp/pdfsum-check/bin/pip install dist/pdfsum-*.whl
/tmp/pdfsum-check/bin/pdfsum --help
/tmp/pdfsum-check/bin/pdfsum doctor
```

### Publicar en PyPI (mantenedores)

**Paso 1 — Test PyPI primero (siempre):**
```bash
export UV_PUBLISH_TOKEN="pypi-..."   # token de https://test.pypi.org
uv publish --publish-url https://test.pypi.org/legacy/ dist/*

# Verificar instalación desde Test PyPI:
pip install --index-url https://test.pypi.org/simple/ pdfsum
```

**Paso 2 — PyPI production (solo si Test PyPI funciona):**
```bash
export UV_PUBLISH_TOKEN="pypi-..."   # token de https://pypi.org
uv publish dist/*
```

> **Automatización**: el workflow `.github/workflows/publish.yml` ejecuta
> este flujo automáticamente al crear un tag `vX.Y.Z` (ver la sección
> "Versionado semántico" en `CHANGELOG.md` y `CONTRIBUTING.md`). Requiere
> el secret `PYPI_API_TOKEN` configurado en GitHub → Settings → Secrets.

---

## 8. Cómo distribuir el proyecto (repo local, sin remoto)

El proyecto vive en un **repositorio git local**. Para entregarlo a un tercero
sin publicarlo en GitHub/GitLab:

**Opción A — git bundle (preserva historial y tags):**
```bash
git bundle create pdfsum.bundle --all
# el receptor:
git clone pdfsum.bundle pdfsum && cd pdfsum && git checkout master
```

**Opción B — tarball del árbol de trabajo:**
```bash
git archive --format=tar.gz -o pdfsum-src.tar.gz HEAD
```

En ambos casos, el receptor sigue §2–§4 para instalar y verificar.

> Nota: la muestra (`samples/pdfs/`) se incluye para la verificación. Si el
> corpus es sensible, sustitúyela por documentos públicos equivalentes y
> actualiza `samples/control_set.json`.

---

## 10. Ejecutar con Docker / Docker Compose

Alternativa a instalar `poppler`/`tesseract`/Python en el host: el repo
incluye `Dockerfile` + `compose.yml` (PR #1, `bireme/master`, mergeado
2026-08-26; runtime completado en FASE13-DOCKER-OLLAMA-RUNTIME). La imagen
empaqueta `poppler-utils` + `tesseract-ocr` (`por`+`eng`+`spa`) + el paquete
`pdfsum` (con **Pillow incluido**, dependencia real de runtime) instalado
con `pip install .`.

### Vía rápida (recomendada): `bin/pdfsum-docker`

El comando `docker run` completo (imágenes, 3 volúmenes, red) es largo de
recordar. El repo trae un wrapper que lo arma por ti:

```bash
bin/pdfsum-docker doctor
bin/pdfsum-docker run --in ./mis_pdfs --workspace ./data --lang por
bin/pdfsum-docker --build run --in ./mis_pdfs --workspace ./data  # fuerza rebuild
```

Funciona desde cualquier directorio (resuelve la raíz del repo solo, no
depende de tu `$PWD` para los volúmenes fijos `input/output/logs`); las
rutas que le pases en `--in`/`--workspace` sí se resuelven contra tu
`$PWD` de invocación (monta tu directorio actual como `/work` dentro del
contenedor). Usa `--network host` internamente — ver el porqué abajo.

### Solo el contenedor `pdfsum` (build + run, manual)

Si prefieres los comandos `docker` sin el wrapper:

```bash
docker build -t pdfsum .
docker run --rm pdfsum                # equivale a: pdfsum --help
docker run --rm pdfsum pdfsum doctor  # diagnóstico de entorno dentro del contenedor
```

Para procesar tus PDFs, monta `input` (solo lectura) y `output`/`logs`:

```bash
docker run --rm \
  -v "$PWD/input:/input:ro" \
  -v "$PWD/output:/output" \
  -v "$PWD/logs:/logs" \
  pdfsum pdfsum run --in /input --workspace /output --lang por
```

> ⚠️ **`host.docker.internal` requiere que Ollama escuche en todas las
> interfaces, no solo en `127.0.0.1`** (el default de `ollama serve` /
> systemd en muchas instalaciones). Si `pdfsum doctor` dentro del
> contenedor dice "ollama: no responde" pese a tener Ollama corriendo en
> el host, agrega `--network host` al `docker run` (así hace
> `bin/pdfsum-docker`) o reconfigura Ollama con
> `OLLAMA_HOST=0.0.0.0:11434` (`systemctl edit ollama`, requiere sudo).

### Con `docker compose`: dos modos, ambos configurables por `.env`

```bash
cp .env.example .env     # elige/ajusta OLLAMA_HOST (ver comentarios dentro)
```

`compose.yml` define dos servicios: `pdfsum` (siempre) y `ollama` (opt-in,
solo con `--profile gpu`). Ninguno depende forzosamente del otro para
arrancar: el modo se elige con la variable `OLLAMA_HOST` (via `.env` o env
del shell) y, si quieres el Ollama embebido, con `--profile gpu`.

#### Modo A (default) — Ollama del HOST, sin GPU passthrough

Es el default de `compose.yml` (`OLLAMA_HOST` cae a
`http://host.docker.internal:11434` si no se sobreescribe). Requiere tener
un Ollama corriendo en la máquina host (fuera de Docker):

```bash
ollama serve                       # en el host, en otra terminal
ollama pull qwen2.5:7b             # una vez
docker compose up --build          # solo levanta el servicio pdfsum
```

Funciona sin GPU pasada al contenedor ni NVIDIA Container Toolkit — la GPU
(si la usas) la consume el Ollama nativo del host, no Docker.

#### Modo B (bundled) — Ollama en su propio contenedor, con GPU

```bash
echo 'OLLAMA_HOST=http://ollama:11434' > .env
docker compose --profile gpu up --build
```

Levanta también el servicio `ollama` (imagen `ollama/ollama:0.33.0`,
volumen nombrado `ollama_models` para persistir modelos descargados,
`gpus: all`).

`pdfsum` consulta automáticamente `OLLAMA_HOST/api/ps`, por lo que registra los
modelos cargados y la VRAM asignada por Ollama aunque la GPU pertenezca al otro
contenedor. Para observar además utilización física, temperatura, potencia,
ventilador, clocks y throttling mediante `nvidia-smi`, habilita el override:

```bash
docker compose -f compose.yml -f compose.gpu-observability.yml \
  --profile gpu up --build
```

El override es opt-in para que el modo normal siga funcionando en equipos sin
NVIDIA. Requiere NVIDIA Container Toolkit. Si no se habilita, `report.json`
explica que `nvidia-smi` no está disponible, pero mantiene la VRAM reportada por
Ollama. Define `PDFSUM_OLLAMA_METRICS=0` para desactivar la consulta a `/api/ps`.

> ⚠️ **El servicio `ollama` (perfil `gpu`) requiere GPU pasada al
> contenedor** (`gpus: all`), lo que exige el **NVIDIA Container Toolkit**
> instalado y configurado en el host (`nvidia-ctk`), además del driver
> NVIDIA. Verifica con `docker info | grep -i runtime` (debe listar
> `nvidia`) antes de `docker compose --profile gpu up`. Sin el toolkit, usa
> el Modo A (default) en su lugar — caso verificado en esta máquina: GPU
> física presente, toolkit ausente, Modo A funcional.

(En Linux, `host.docker.internal` se resuelve gracias al `extra_hosts:
host-gateway` ya incluido en `compose.yml`; con `docker run` suelto en vez
de compose, añade `--add-host=host.docker.internal:host-gateway`.)

#### Modo C (cloud puro) — sin Ollama en absoluto, backend en la nube

Ni el servicio `ollama` ni un Ollama nativo del host son necesarios para
resumir (sí siguen haciendo falta si quieres el fallback VLM de OCR de
escaneos difíciles — si no hay Ollama alcanzable, degrada a Tesseract):

```bash
echo 'PDFSUM_SUMMARIZER_BACKEND=openrouter' >> .env
echo 'OPENROUTER_API_KEY=sk-or-...' >> .env
docker compose up --build
```

`compose.yml` pasa `PDFSUM_SUMMARIZER_BACKEND`, `OPENAI_API_KEY`,
`OPENROUTER_API_KEY` y `ANTHROPIC_API_KEY` al contenedor `pdfsum` desde el
entorno/`.env` del host (vacías si no las defines) — nunca hardcodeadas en
`compose.yml`. Detalle de backends: Sección 2 (Opción B).

### Verificado (2026-08-26) — qué funciona

| Comando | Resultado |
|---|---|
| `docker build -t pdfsum .` | ✅ OK (incluye Pillow) |
| `docker run --rm pdfsum` / `pdfsum --help` | ✅ OK |
| `docker run --rm pdfsum pdfsum doctor` | ✅ OK |
| `docker compose config` / `--profile gpu config` | ✅ ambos manifiestos válidos |
| `pdfsum transcribe` sobre PDF nativo/escaneado simple | ✅ OK |
| `pdfsum transcribe` sobre escaneado con fallback OCR por región (antes fallaba con `ModuleNotFoundError: No module named 'PIL'`) | ✅ OK tras mover `pillow` a `dependencies` en `pyproject.toml` |
| `docker compose --profile gpu up` (Ollama embebido, GPU real) | ⚠️ no verificado end-to-end en esta máquina (sin `nvidia-container-toolkit`); `docker compose --profile gpu config` sí valida |
| `docker run -e PDFSUM_SUMMARIZER_BACKEND=openrouter -e OPENROUTER_API_KEY=... pdfsum pdfsum doctor` (Modo C, cloud puro) | ✅ OK — detecta el backend, confirma la API key, resume sin Ollama |

Detalle técnico del fix y criterios ejecutables:
`evals/eval-spec-fase13-docker-ollama-runtime.yaml` (Pillow/Ollama
configurable) y `evals/eval-spec-fase14-backends-cloud.yaml` (Modo C,
backends cloud).

---

## 11. Reproducibilidad: qué está fijado y qué no

| Fijado (determinista) | No fijado (varía) |
|---|---|
| Clasificación tipo/idioma (reglas) | Redacción del resumen (LLM) |
| Estrategia de porción / bloques | Orden exacto de frases |
| Extracción de abstracts (regex) | Términos sinónimos elegidos |
| Contrato JSON de salida | — |
| Criterios de QA y de aceptación | — |

La verificación se centra en lo **objetivo y estable** (estructura, idioma,
tipo, cobertura de términos), no en la redacción literal.
