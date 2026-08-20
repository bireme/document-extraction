# Guía rápida de uso — pdfsum

Convertir PDFs en resúmenes estructurados, 100 % local (sin API).
Todo lo necesario en **una página**. Instalación detallada: `INSTALL.md`.

---

## Uso principal

```bash
pdfsum run --in /ruta/a/tus/pdfs --workspace ./datos --lang por
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
| API de consulta local | `pdfsum serve --batch-dir ./data/summaries --port 8765` |
| Diagnóstico de entorno | `pdfsum doctor` |
| Verificar instalación | `pdfsum verify --workspace ./_v` |

---

## Opciones clave de `run`

```bash
--lang por|spa|eng            idioma del OCR (el resumen va en el idioma del doc)
--model qwen2.5:7b            modelo de resumen (por defecto)
--long-strategy blocks        manuales largos: resumir por bloques (cubre todo)
```

**Manual largo completo:**
```bash
pdfsum run --in ./manuales --workspace ./data_manuales --lang por --long-strategy blocks
```

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
