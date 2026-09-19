# API de comandos PDF

OFI9 selecciona los registros y obtiene `id` + URL desde MongoDB. ServerIA-stg
recibe `id`, `command` y una fuente (`url` o `folder`), prepara el PDF en un
directorio temporal y despacha el pipeline Python
existente de `extract-abstracts`, `transcribe` o `run`. OFI9 persiste la respuesta.
**ServerIA no accede a MongoDB ni utiliza `PDFSUM_MONGODB_URI`.**

```text
OFI9 (selección) → ServerIA (descarga o copia → dispatcher → pipeline → limpieza)
                ← respuesta JSON
OFI9 → MongoDB (persistencia)
```

## Inicio

El Dockerfile actual ya incluye FastAPI y Uvicorn mediante `pdfsum[service]`.
Fuera de Docker: `pip install '.[service]'`.

```bash
OLLAMA_HOST=http://ollama:11434 pdfsum processing-api \
  --host 0.0.0.0 --port 8766 --workspace /output --logs-dir /logs \
  --backend ollama --model qwen2.5:7b --vlm-model qwen3-vl:8b-instruct \
  --lang por+eng+spa
```

Se reutilizan las fábricas y `.pdfsum-config.json` del CLI: backend/modelo,
modelo VLM, idiomas OCR y `abstract_refine_context_chars`. Las credenciales de
backends cloud mantienen su configuración habitual por variables de entorno.
Los modelos deben estar disponibles en Ollama; el OCR conserva su fallback a
Tesseract cuando el VLM no está disponible. Los adaptadores se crean por solicitud.

En la composición externa, configura el servicio `pdfsum` así, conservando los
volúmenes y la conexión a Ollama existentes:

```yaml
command: ["pdfsum", "processing-api", "--host", "0.0.0.0", "--port", "8766", "--workspace", "/output", "--logs-dir", "/logs"]
ports:
  - "8766:8766"
environment:
  OLLAMA_HOST: http://ollama:11434
```

Para usar solo URL no hace falta montar `/input`. Para archivos locales, monta
el directorio de entrada, preferiblemente en modo de solo lectura.
`--input-root` configura su ubicación y tiene `/input` como valor predeterminado.
El servicio no incorpora autenticación; limita el acceso a OFI9 mediante la red/firewall o un proxy con
TLS y autenticación. El host por defecto del CLI es `127.0.0.1`.

El comando anterior `extract-abstracts-api` se sustituye por `processing-api`.
El comando `pdfsum api` conserva su servicio asíncrono previo, sin cambios.
`--long-strategy` admite `excerpt` (predeterminado), `blocks` y `hierarchical`
y se aplica solamente a `run`. Backend/modelo se aplican a `run` y
`extract-abstracts`; `transcribe` no crea un LLM de resumen. Idiomas y modelo VLM
se aplican a los tres comandos. El contexto de revisión se aplica solo a abstracts.

## Contrato

Único endpoint de procesamiento: `POST /api/pdfsum`.

```bash
curl --fail-with-body http://serveria-stg:8766/api/pdfsum \
  -H 'Content-Type: application/json' \
  -d '{"id":79665,"command":"extract-abstracts","url":"https://servidor.ejemplo/documento.pdf"}'
```

```bash
curl --fail-with-body http://serveria-stg:8766/api/pdfsum \
  -H 'Content-Type: application/json' \
  -d '{"id":79665,"command":"transcribe","url":"https://servidor.ejemplo/documento.pdf"}'

curl --fail-with-body http://serveria-stg:8766/api/pdfsum \
  -H 'Content-Type: application/json' \
  -d '{"id":79665,"command":"run","url":"https://servidor.ejemplo/documento.pdf"}'
```

`command` es obligatorio y admite solamente `extract-abstracts`, `transcribe` y
`run`. `summarize`, comandos de shell y valores desconocidos reciben HTTP 422
antes de descargar. `summarize` requiere un contrato de texto que se decidirá
posteriormente; esta API no descarga archivos de texto. El endpoint anterior
`/api/extract-abstracts` fue eliminado.

La solicitud debe contener `id`, `command` y exactamente una fuente: `url` o
`folder`. Se rechazan ambas fuentes juntas, la ausencia de fuente y los campos
adicionales. Los tres comandos admiten ambas fuentes.

URL:

```json
{
  "id": 75798,
  "command": "extract-abstracts",
  "url": "https://example.org/documento.pdf"
}
```

Carpeta local:

```json
{
  "id": 75798,
  "command": "extract-abstracts",
  "folder": "MS-all"
}
```

La API busca `<input_root>/MS-all/75798_*.pdf`: el nombre debe comenzar
literalmente con `75798_` y terminar con `.pdf`. Debe existir exactamente un
archivo regular; varias coincidencias producen un error de ambigüedad.
`folder` admite solamente letras ASCII, números, `_`, `-` y `.`, excepto los
valores completos `.` y `..`. No admite rutas ni separadores. Se rechazan enlaces
simbólicos de carpeta o de archivos coincidentes con HTTP 409.
Solo se copia el PDF seleccionado a `<workspace-temporal>/input/<run_id>.pdf`;
el pipeline recibe esa copia y el original permanece intacto.

`id` admite un entero positivo o texto no vacío de hasta 256 caracteres, sin caracteres de control.
No se convierte su tipo en la respuesta. Para archivos locales se compara como
prefijo literal del nombre; nunca se interpreta como ruta ni patrón.
`url` debe ser HTTP/HTTPS sin credenciales embebidas. El servicio no recibe opciones de procesamiento por
solicitud: las configura el operador al iniciar el proceso.

HTTP 200:

```json
{
  "id": 79665,
  "command": "extract-abstracts",
  "status": "completed",
  "result": {
    "doc_id": "referencia-interna-aleatoria",
    "status": "found",
    "source_kind": "nativo",
    "abstracts": [
      {"lang": "es", "header": "Resumen", "text": "Texto original…", "keywords": ""}
    ]
  }
}
```

Para `extract-abstracts`, `result` es el contenido exacto de `abstracts/<doc_id>.json`, sin otra
representación ni contenido del reporte agregado. `result.doc_id` identifica la
ejecución interna; `id` es la identidad de OFI9. Un documento sin resumen devuelve
HTTP 200 con `result.status = "not_found"` y `abstracts = []`. Una falla de revisión
LLM conserva la extracción determinista, igual que el CLI, y queda registrada.

Para `transcribe`, `result` es una string con el contenido UTF-8 completo de
`ocr/<doc_id>.txt`, incluidos sus saltos de línea. Para `run`, es el JSON exacto
de `summaries/<doc_id>.json`, con los campos de resumen, metadatos y `_qa` que
produce el pipeline. No se devuelve el reporte agregado del lote. Si `run`
registra un documento fallido, la API devuelve un error de procesamiento.

El dispatcher llama directamente `extract_abstracts_from_pdfs`, `transcribe_pdfs`
o `run_batch_pdfs`; no invoca el CLI ni construye comandos de shell. La descarga,
el aislamiento, los errores y la limpieza son comunes a los tres comandos.

Errores:

```json
{
  "id": 79665,
  "command": "extract-abstracts",
  "status": "failed",
  "phase": "descarga",
  "error_type": "DownloadError",
  "error": "No se pudo descargar el PDF"
}
```

| HTTP | phase | error_type | Motivo |
| --- | --- | --- | --- |
| 422 | validacion | ValidationError | Campos, identidad, JSON, URL o folder inválidos; destino literal prohibido |
| 404 | seleccion | SelectionError | Carpeta o PDF del id inexistente |
| 409 | seleccion | SelectionError | Varios PDFs coincidentes o enlace simbólico |
| 500 | seleccion | SelectionError | Fallo inesperado de lectura o copia |
| 502 | descarga | DownloadError | DNS/destino bloqueado, HTTP, timeout, tamaño o contenido inválido |
| 500 | procesamiento | ProcessingError | Preparación, transcripción o procesamiento fallidos |
| 500 | limpieza | CleanupError | No se pudieron eliminar los temporales; revisar el disco |

Los errores incluyen `command` cuando es válido; si falta o no está permitido,
devuelven `command: null` para no reflejar valores arbitrarios sensibles.
Los errores preservan `id` cuando puede leerse del JSON. Si falta o el JSON no se
puede interpretar, devuelven `id: null`. No incluyen excepciones originales,
stack traces, URLs, prompts ni tokens. Un fallo de limpieza tiene prioridad sobre
cualquier respuesta anterior y queda registrado.

## Descarga y aislamiento

- Streaming en bloques de 64 KiB; límite predeterminado de 100 000 000 bytes,
  configurable con `--max-download-bytes`. Se controla con y sin `Content-Length`.
- `--download-timeout` (30 segundos) limita operaciones de socket. No es un plazo
  total de descarga y no limita la resolución DNS del sistema ni el procesamiento.
- Solo HTTP 200; se rechazan archivos vacíos, longitud incoherente, Content-Type
  incompatible, encabezado distinto de `%PDF-x.y` o ausencia de `%%EOF` al final.
  Es una validación preliminar; el pipeline interpreta el PDF.
- SSRF: rechaza localhost, loopback, redes privadas, link-local, metadata y otras
  direcciones no globales. Valida **todos** los resultados DNS antes de conectar
  y conecta a la IP validada sin otra resolución. Conserva hostname, SNI y
  verificación TLS. Cada redirect vuelve a validar el destino, con límite de saltos.
  No utiliza proxies del entorno.
- Cada solicitud tiene un directorio temporal propio y nombres aleatorios. Dos
  solicitudes con el mismo `id` se procesan independientemente. Se eliminan PDF,
  OCR, JSON y otros temporales tanto al completar como al fallar.
- Con `--logs-dir`, conserva eventos y reporte operativo sin contenido documental
  bajo un subdirectorio aleatorio por ejecución. Sin esa opción, solo permanece
  el log estándar. El access log de Uvicorn está desactivado para evitar registrar
  query strings. La rotación de logs persistentes corresponde al operador.

La respuesta es síncrona: OFI9 y cualquier proxy deben esperar todo el OCR y la
revisión. No hay cola, reservas, persistencia de jobs, deduplicación ni reintentos
automáticos. FastAPI ejecuta el trabajo en su pool de threads; dimensiona la
concurrencia según memoria/GPU. Una interrupción abrupta del proceso puede dejar
un directorio temporal; no se elimina automáticamente al reiniciar.
