# Guía rápida de uso — pdfsum

Convertir PDFs en resúmenes estructurados, 100 % local (sin API).
Todo lo necesario en **una página**. Instalación detallada: `INSTALL.md`.

---

## Uso principal

```bash
pdfsum run --in /ruta/a/tus/pdfs --workspace ./datos --lang por+eng+spa
```

Apuntas a una carpeta de PDFs y la app: transcribe (OCR si hace falta) →
resume en el idioma del documento y con la plantilla de su tipo → valida →
reporta. Resultados:

```
./datos/ocr/<doc_id>.txt           transcripciones (cacheadas)
./datos/summaries/<doc_id>.json    un resumen por documento (+ su QA)
./datos/summaries/report.json      métricas del lote
```

---

## Preparación (una vez)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pdfsum doctor     # ¿tengo poppler, tesseract, ollama y los modelos?
pdfsum verify     # ¿produce resultados de referencia? (esperado: PASS)
```

**Requisitos:** poppler + Tesseract (OCR) + **Ollama con `qwen2.5:7b`**
(resúmenes) y `qwen3-vl:8b-instruct` (escaneos difíciles). `doctor` te dice
qué falta.

---

## Ejemplos ejecutables (con la muestra incluida)

La app trae 2 PDFs de muestra en `samples/pdfs/` para probar sin buscar docs:

```bash
# 1) Flujo completo sobre la muestra incluida
pdfsum run --in samples/pdfs --workspace ./demo --lang por
#   -> ./demo/ocr/*.txt + ./demo/summaries/*.json + report.json

# 2) Ver el resumen de uno de los documentos
cat ./demo/summaries/58739_deixar_fumar.json | python3 -m json.tool | head -30

# 3) Exportar el lote a registros de catalogación LILACS (borrador)
pdfsum export --in ./demo/summaries --out ./demo/lilacs.json

# 3b) Registros bibliográficos BIBFRAME (JSON-LD), uno por documento
#     (--pdfs opcional: usa la metadata embebida del PDF con precedencia)
pdfsum bibframe --in ./demo/summaries --pdfs samples/pdfs --out ./demo/bibframe

# 4) Consultar por API local
pdfsum serve --batch-dir ./demo/summaries --port 8765 &
curl http://127.0.0.1:8765/api/summaries
curl http://127.0.0.1:8765/api/summaries/58739_deixar_fumar
curl http://127.0.0.1:8765/api/report
```

**Con tus propios PDFs:** cambia `samples/pdfs` por tu carpeta.

---

## Comandos (referencia)

| Quiero | Comando |
|---|---|
| **Resumir mis PDFs** | `pdfsum run --in ./pdfs --workspace ./data --lang por` |
| Solo transcribir | `pdfsum transcribe --in ./pdfs --workspace ./data` |
| Resumir un texto ya transcrito | `pdfsum summarize --text doc.txt --pages 4 --out r.json` |
| Re-resumir lote de .txt | `pdfsum batch --in ./textos --out ./resumenes` |
| Export LILACS (borrador) | `pdfsum export --in ./data/summaries --out lilacs.json` |
| Registros BIBFRAME JSON-LD (borrador) | `pdfsum bibframe --in ./data/summaries --pdfs ./pdfs --out ./data/bibframe` |
| API de consulta local | `pdfsum serve --batch-dir ./data/summaries --port 8765` |
| Diagnóstico de entorno | `pdfsum doctor` |
| Verificar instalación | `pdfsum verify --workspace ./_v` |

---

## Opciones clave de `run`

```bash
--lang por+eng+spa            idioma(s) OCR Tesseract, combinables con '+'
                               (default: por+eng+spa; el resumen va en el
                               idioma del doc, detectado aparte)
--model qwen2.5:7b            modelo de resumen (por defecto)
--long-strategy ESTRATEGIA    elección del usuario por recursos/necesidades
```

### Estrategias de procesamiento para documentos largos (>40K caracteres)

La decisión entre estrategias es tuya: depende de **tus recursos** y **qué necesitas**.

| Estrategia | Contenido | Tiempo | Calidad | Caso de uso |
|---|---|---|---|---|
| **`excerpt`** (default) | ~3% del doc | ~15s | Prefacio + intro | Demo rápido, resúmenes ultraconcisos, poc |
| **`blocks`** | 100% del doc | ~60s | Cobertura total | Manuales medianos, presupuesto moderado |
| **`hierarchical`** | 100% del doc | ~600s (10 min) | **Cobertura + coherencia por capítulos** | Libros con estructura clara (capítulos), máxima calidad |

**Ejemplos:**

```bash
# Resumen rápido de un folleto (default)
pdfsum run --in ./folletos --workspace ./data

# Manual largo → bloques (100% cobertura, tiempo medio)
pdfsum run --in ./manuales --workspace ./data --long-strategy blocks

# Libro de 300+ págs → jerárquico (100% cobertura + coherencia capítulos)
pdfsum run --in ./libros --workspace ./data --long-strategy hierarchical
```

**Nota:** Estrategias coexisten. El modelo `hierarchical` detecta capítulos reales
de documentos; si no encuentra estructura, degrada automáticamente a `blocks`.

**Corpus con más idiomas (ej. añadir francés):** instala el paquete
(`tesseract-ocr-fra`) y añade el código: `--lang por+eng+spa+fra`.

---

## Personalizar defaults (sin tocar CLI)

Si siempre usas la misma estrategia, puedes configurarla en un archivo
(los flags CLI siempre prevalecen):

**En tu directorio de trabajo:**
```bash
cat > .pdfsum-config.json <<EOF
{
  "long_strategy": "hierarchical",
  "model": "qwen2.5:7b",
  "lang": "por+eng+spa"
}
EOF

# Ahora todos los comandos usan hierarchical por defecto
pdfsum run --in ./libros --workspace ./data
# (es equivalente a: pdfsum run ... --long-strategy hierarchical)
```

**En tu home (global):**
```bash
cp .pdfsum-config.json ~/.pdfsum-config.json
# Aplica a todo proyecto (puedes sobreescribir en un .pdfsum-config.json local)
```

Copia tu configuración desde `.pdfsum-config.example.json` en el repo.

---

## Buenas prácticas

- **Idempotente:** re-ejecutar no repite OCR (usa `ocr/*.txt` cacheados).
  Para regenerar desde cero, borra el workspace.
- **Tiempos:** los nativos se extraen al instante; los escaneados se resuelven
  con OCR por región (Tesseract o VLM). Un folleto escaneado de pocas páginas
  puede tardar ~1–3 min con el VLM local; re-ejecutar no lo repite (cacheado).
- **Nativos** se extraen directo; **escaneados** pasan por OCR con segmentación
  por columnas y fallback al modelo de visión en páginas difíciles.
- **Idiomas:** el resumen sale en el idioma del documento; los abstracts de
  origen multilingües se preservan verbatim.
- Si falta Ollama/modelo, los comandos se detienen con un mensaje claro de qué
  instalar (ver también `pdfsum doctor`).
