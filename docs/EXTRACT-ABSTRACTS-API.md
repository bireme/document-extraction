# API de extracción de resúmenes existentes

OFI9 selecciona los registros y obtiene `id` + URL desde MongoDB. ServerIA-stg
recibe esos dos campos, descarga el PDF, ejecuta el pipeline existente de
`extract-abstracts` y devuelve su JSON principal. OFI9 persiste la respuesta.
**ServerIA no accede a MongoDB ni utiliza `PDFSUM_MONGODB_URI`.**

```text
OFI9 (selección) → ServerIA (descarga → OCR/VLM → extracción → revisión → JSON)
                ← respuesta JSON
OFI9 → MongoDB (persistencia)
```

## Inicio

El Dockerfile actual ya incluye FastAPI y Uvicorn mediante `pdfsum[service]`.
Fuera de Docker: `pip install '.[service]'`.

```bash
OLLAMA_HOST=http://ollama:11434 pdfsum extract-abstracts-api \
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
command: ["pdfsum", "extract-abstracts-api", "--host", "0.0.0.0", "--port", "8766", "--workspace", "/output", "--logs-dir", "/logs"]
ports:
  - "8766:8766"
environment:
  OLLAMA_HOST: http://ollama:11434
```

No hace falta montar `/input`: ServerIA descarga el PDF. El servicio no incorpora
autenticación; limita el acceso a OFI9 mediante la red/firewall o un proxy con
TLS y autenticación. El host por defecto del CLI es `127.0.0.1`.

## Contrato

Único endpoint de procesamiento: `POST /api/extract-abstracts`.

```bash
curl --fail-with-body http://serveria-stg:8766/api/extract-abstracts \
  -H 'Content-Type: application/json' \
  -d '{"id":79665,"url":"https://servidor.ejemplo/documento.pdf"}'
```

La solicitud debe contener exactamente `id` y `url`. `id` admite un entero
positivo o texto no vacío de hasta 256 caracteres, sin caracteres de control.
No se convierte su tipo ni se usa para construir rutas. `url` debe ser HTTP/HTTPS
sin credenciales embebidas. El servicio no recibe opciones de procesamiento por
solicitud: las configura el operador al iniciar el proceso.

HTTP 200:

```json
{
  "id": 79665,
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

`result` es el contenido exacto de `abstracts/<doc_id>.json`, sin otra
representación ni contenido del reporte agregado. `result.doc_id` identifica la
ejecución interna; `id` es la identidad de OFI9. Un documento sin resumen devuelve
HTTP 200 con `result.status = "not_found"` y `abstracts = []`. Una falla de revisión
LLM conserva la extracción determinista, igual que el CLI, y queda registrada.

Errores:

```json
{
  "id": 79665,
  "status": "failed",
  "phase": "download",
  "error_type": "DownloadError",
  "error": "No se pudo descargar el PDF"
}
```

| HTTP | phase | error_type | Motivo |
| --- | --- | --- | --- |
| 422 | validation | ValidationError | Campos, identidad, JSON o URL inválidos; destino literal prohibido |
| 502 | download | DownloadError | DNS/destino bloqueado, HTTP, timeout, tamaño o contenido inválido |
| 500 | processing | ProcessingError | Preparación, transcripción o procesamiento fallidos |
| 500 | cleanup | CleanupError | No se pudieron eliminar los temporales; revisar el disco |

Los errores preservan `id` cuando puede leerse del JSON. Si falta o el JSON no se
puede interpretar, devuelven `id: null`. No incluyen excepciones originales,
stack traces, URLs, prompts ni tokens. Un fallo de cleanup tiene prioridad sobre
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
