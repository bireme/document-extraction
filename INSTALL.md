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
- Configura acceso a servicios de modelos remotos (OpenAI API, Anthropic, etc.)
- Requiere API key de proveedor externo + plan pagado
- Ver Sección 5 (Configuración de Modelos Remotos)
- Ideal si no tienes GPU o quieres máxima privacidad sin inversión local

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

#### ⚠️ Opción B: Modelos Remotos (OpenAI, Anthropic, etc.)

**Requiere:**
- API key de proveedor (OpenAI, Anthropic, HuggingFace, etc.)
- Conexión a internet constante
- Plan pagado en el proveedor
- Sin inversión en GPU local

**Configuración:**
```bash
# Crear archivo .pdfsum-config.json en casa
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "openai",
  "openai_api_key": "sk-...",
  "openai_model": "gpt-4-turbo",
  "transcriber_backend": "openai"
}
EOF

# O variables de entorno
export OPENAI_API_KEY="sk-..."
export PDFSUM_SUMMARIZER_BACKEND="openai"
```

**Ventajas:**
- ✅ No requiere GPU
- ✅ Modelos de última generación (GPT-4, Claude 3, etc.)
- ✅ Escalable sin límite local

**Desventajas:**
- ❌ Costo por uso (caro si procesas muchos documentos)
- ❌ Datos salen a servidores externos
- ❌ Dependencia de internet
- ❌ Latencia de red

**Proveedores recomendados:**
- OpenAI (gpt-4-turbo, gpt-4o)
- Anthropic (claude-3-opus)
- HuggingFace (modelos open source)
- Replicate (modelos open source hosted)

#### 🤔 ¿Cuál elegir?

| Escenario | Recomendación |
|---|---|
| Tengo GPU ≥ 8 GB | **Ollama local** (mejor relación costo/beneficio) |
| No tengo GPU | **Servicios remotos** (OpenAI, Anthropic, etc.) |
| Procesamiento ocasional | **Servicios remotos** (costo bajo) |
| Procesamiento masivo | **Ollama local** (sin costos recurrentes) |
| Privacidad crítica | **Ollama local** (datos en casa) |
| Máxima calidad | **OpenAI/Anthropic** (GPT-4, Claude 3) |

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
- Si ves `XX ollama: no encontrado` → configura modelos remotos (Sección 2, Opción B)
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

## 9. Reproducibilidad: qué está fijado y qué no

| Fijado (determinista) | No fijado (varía) |
|---|---|
| Clasificación tipo/idioma (reglas) | Redacción del resumen (LLM) |
| Estrategia de porción / bloques | Orden exacto de frases |
| Extracción de abstracts (regex) | Términos sinónimos elegidos |
| Contrato JSON de salida | — |
| Criterios de QA y de aceptación | — |

La verificación se centra en lo **objetivo y estable** (estructura, idioma,
tipo, cobertura de términos), no en la redacción literal.
