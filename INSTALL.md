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
- GPU con **≥ 8 GB VRAM** (probado en RTX 5060 Laptop, 8 GB) + ~16 GB RAM.
- Con GPU superior, los modelos corren igual o más rápido.

### Software de sistema
- **Python ≥ 3.10**
- **poppler-utils** (`pdftotext`, `pdfinfo`, `pdftoppm`) — requisito duro.
- **Tesseract OCR** + idiomas del corpus (`por`, `spa`, `eng`, …) — para
  documentos escaneados.
- **Ollama** (runtime de modelos locales) + los modelos:
  - `qwen2.5:7b` — generación de resúmenes (texto).
  - `qwen3-vl:8b-instruct` — OCR de escaneos difíciles (visión, opcional).

```bash
# Debian/Ubuntu
sudo apt install python3 python3-venv poppler-utils \
     tesseract-ocr tesseract-ocr-por tesseract-ocr-spa tesseract-ocr-eng

# Ollama (ver https://ollama.com) y modelos
ollama pull qwen2.5:7b
ollama pull qwen3-vl:8b-instruct
```

---

## 2. Instalación de la aplicación

El núcleo no tiene dependencias Python (solo stdlib): se instala directo.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .          # desde la raíz del proyecto (donde está pyproject.toml)
pdfsum --help             # el comando 'pdfsum' queda disponible
```

---

## 3. Verificar el entorno

```bash
pdfsum doctor
```
Lista cada dependencia como `[duro]` u `[opc]` y dice si el **entorno mínimo**
(flujo con PDFs nativos) está listo. Los `[opc]` que falten limitan capacidades
(p. ej. sin `tesseract` no se procesan escaneos; sin `ollama` no hay resumen
real).

---

## 4. Verificar que obtiene resultados similares

La aplicación incluye una **muestra** (`samples/pdfs/`) y un **set de control**
(`samples/control_set.json`) con expectativas verificables.

```bash
pdfsum verify --workspace ./_verify --lang por
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

## 5. Uso real sobre tus propios PDFs

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

## 6. Cómo distribuir el proyecto (repo local, sin remoto)

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

## 7. Reproducibilidad: qué está fijado y qué no

| Fijado (determinista) | No fijado (varía) |
|---|---|
| Clasificación tipo/idioma (reglas) | Redacción del resumen (LLM) |
| Estrategia de porción / bloques | Orden exacto de frases |
| Extracción de abstracts (regex) | Términos sinónimos elegidos |
| Contrato JSON de salida | — |
| Criterios de QA y de aceptación | — |

La verificación se centra en lo **objetivo y estable** (estructura, idioma,
tipo, cobertura de términos), no en la redacción literal.
