# PDFSum Worker

Worker de orquestación para procesamiento remoto de documentos con PDFSum.

El worker obtiene la información necesaria de los documentos, envía la solicitud al servidor remoto de procesamiento y persiste el resultado en MongoDB.

El worker no procesa los PDFs localmente.

## Arquitectura

```text
MongoDB
   │
   ▼
Worker
   │
   │ POST /api/pdfsum
   ▼
PDFSum Processing API
   │
   │ JSON
   ▼
Worker
   │
   ▼
MongoDB
```

El origen del PDF puede configurarse en dos modos:

```text
url
folder
```

En modo `url`, el worker consulta `electronic_address` en MongoDB y selecciona una URL PDF válida.

En modo `folder`, el worker no necesita seleccionar una URL del documento. Envía a la API el `id`, el `command` y el nombre lógico de la carpeta donde se encuentra el PDF.

## Responsabilidades

El worker se encarga de:

* crear y controlar jobs en `document_extraction_jobs`;
* llamar al endpoint `POST /api/pdfsum`;
* persistir resultados y fallos en MongoDB;
* controlar intentos de procesamiento;
* recuperar jobs abandonados en estado `processing`;
* seleccionar una URL PDF desde `electronic_address` cuando `PDFSUM_INPUT_MODE=url`;
* enviar el nombre de la carpeta de entrada cuando `PDFSUM_INPUT_MODE=folder`.

## Requisitos

Para ejecutar el worker solamente es necesario tener:

* Docker;
* Docker Compose;
* acceso de red a MongoDB;
* acceso de red al servidor donde se ejecuta PDFSum Processing API.

No es necesario instalar Python ni las dependencias del worker directamente en el host.

## Configuración

Copie el archivo de ejemplo:

```bash
cp .env.example .env
```

Edite `.env` y configure las variables necesarias.

Ejemplo para usar URLs desde MongoDB:

```dotenv
PDFSUM_MONGODB_URI=mongodb://usuario:senha@mongodb.example:27017/
PDFSUM_SERVER_URL=http://servidor-pdfsum:8766

PDFSUM_INPUT_MODE=url
PDFSUM_INPUT_FOLDER=
```

Ejemplo para usar PDFs disponibles en una carpeta del servidor de procesamiento:

```dotenv
PDFSUM_MONGODB_URI=mongodb://usuario:senha@mongodb.example:27017/
PDFSUM_SERVER_URL=http://servidor-pdfsum:8766

PDFSUM_INPUT_MODE=folder
PDFSUM_INPUT_FOLDER=MS-all
```

### `PDFSUM_MONGODB_URI`

URI de conexión al MongoDB utilizado por el worker.

El valor real no debe almacenarse en Git.

### `PDFSUM_SERVER_URL`

URL base del servidor que ejecuta PDFSum Processing API.

El worker agrega automáticamente `/api/pdfsum` cuando la URL configurada no contiene el endpoint completo.

### `PDFSUM_INPUT_MODE`

Define cómo el worker informa a la API dónde obtener el PDF.

Valores admitidos:

```text
url
folder
```

El valor predeterminado es:

```text
url
```

#### Modo `url`

En este modo el worker consulta el registro correspondiente en MongoDB, lee `electronic_address` y selecciona una URL PDF válida, priorizando HTTPS.

La solicitud enviada a la API tiene esta forma:

```json
{
  "id": 75798,
  "command": "extract-abstracts",
  "url": "https://example.org/documento.pdf"
}
```

En este modo `PDFSUM_INPUT_FOLDER` puede permanecer vacío.

#### Modo `folder`

En este modo el worker no utiliza `electronic_address` para localizar el PDF.

La solicitud enviada a la API tiene esta forma:

```json
{
  "id": 75798,
  "command": "extract-abstracts",
  "folder": "MS-all"
}
```

La API es responsable de localizar el archivo correspondiente dentro de su directorio de entrada.

Por ejemplo, si la API utiliza `/input` como raíz y recibe:

```text
id: 75798
folder: MS-all
```

buscará un único PDF con el formato:

```text
/input/MS-all/75798_*.pdf
```

Ejemplo válido:

```text
/input/MS-all/75798_avaliacao_atraumatico_piaui.pdf
```

### `PDFSUM_INPUT_FOLDER`

Nombre lógico de la carpeta utilizado solamente cuando:

```text
PDFSUM_INPUT_MODE=folder
```

Ejemplo:

```dotenv
PDFSUM_INPUT_FOLDER=MS-all
```

Debe contener solamente el nombre de la carpeta, no una ruta completa.

Correcto:

```text
MS-all
```

Incorrecto:

```text
/MS-all
/input/MS-all
MS-all/subdir
```

Cuando `PDFSUM_INPUT_MODE=url`, esta variable puede permanecer vacía:

```dotenv
PDFSUM_INPUT_FOLDER=
```

## Selección de documentos

Cree un archivo `ids.txt` en el directorio del worker con los IDs que se procesarán.

Ejemplo:

```text
79665
79662
79667
```

También es posible separar los IDs por espacios.

El archivo `ids.txt` no se versiona en Git.

## Construcción de la imagen

Construya la imagen Docker:

```bash
docker compose build
```

## Ejecución

Para procesar los IDs definidos en `ids.txt`:

```bash
docker compose run --rm pdfsum-worker
```

El container procesa el lote y termina después de finalizar los documentos.

El comando configurado por defecto en `compose.yaml` es:

```text
extract-abstracts
```

## Comandos admitidos

El worker admite los siguientes comandos de PDFSum:

* `extract-abstracts`
* `transcribe`
* `run`

### Extraer resúmenes

El comportamiento predeterminado del Compose es equivalente a:

```bash
docker compose run --rm pdfsum-worker \
  --command extract-abstracts \
  --ids-file /config/ids.txt
```

### Transcribir documentos

```bash
docker compose run --rm pdfsum-worker \
  --command transcribe \
  --ids-file /config/ids.txt
```

### Ejecutar el pipeline completo

```bash
docker compose run --rm pdfsum-worker \
  --command run \
  --ids-file /config/ids.txt
```

## Sobrescribir el modo de entrada por CLI

También es posible definir el modo de entrada por argumentos de línea de comandos.

Ejemplo usando URLs:

```bash
docker compose run --rm pdfsum-worker \
  --command extract-abstracts \
  --ids-file /config/ids.txt \
  --input-mode url
```

Ejemplo usando una carpeta:

```bash
docker compose run --rm pdfsum-worker \
  --command extract-abstracts \
  --ids-file /config/ids.txt \
  --input-mode folder \
  --input-folder MS-all
```

Los argumentos de CLI permiten sobrescribir la configuración equivalente definida en las variables de entorno.

## MongoDB

Por defecto, el worker utiliza:

```text
database: FIs_02_converted
colección fuente: mis
colección de jobs: document_extraction_jobs
```

La colección `mis` se utiliza como fuente de información cuando el modo de entrada necesita consultar datos del documento, como ocurre con `PDFSUM_INPUT_MODE=url`.

Los estados y resultados del procesamiento se almacenan en `document_extraction_jobs`.

## Estados de los jobs

El ciclo básico de un job es:

```text
pending
   │
   ▼
processing
   │
   ├──► completed
   │
   └──► failed
```

Cada combinación de:

```text
id + command
```

identifica un job.

El worker crea un índice único para esa combinación.

## Reintentos

Por defecto, cada job puede realizar hasta 3 intentos.

Un job en estado `failed` puede volver a procesarse mientras no haya alcanzado el número máximo de intentos.

El valor puede modificarse con:

```text
--max-attempts
```

## Recuperación de jobs abandonados

Si una ejecución se interrumpe mientras un job está en estado `processing`, el worker puede recuperarlo posteriormente.

Por defecto, un job se considera abandonado tras 60 minutos sin renovar su reserva. Los jobs históricos sin reserva usan la fecha de inicio.

Este valor puede modificarse con:

```text
--stale-after-minutes
```

## Timeouts

El worker utiliza dos timeouts diferentes para comunicarse con el servidor de procesamiento.

El timeout de conexión predeterminado es:

```text
10 segundos
```

El timeout de espera del procesamiento remoto es:

```text
1800 segundos
```

es decir, 30 minutos.

Pueden modificarse con:

```text
--connect-timeout
--read-timeout
```

## Ejecución con opciones adicionales

Las opciones disponibles pueden consultarse con:

```bash
docker compose run --rm pdfsum-worker --help
```

## Archivos

La estructura mínima de esta branch es:

```text
.
├── .env.example
├── .gitignore
├── Dockerfile
├── README.md
├── compose.yaml
├── pdfsum_worker.py
└── worker_requirements.txt
```

Los siguientes archivos son locales y no deben versionarse:

```text
.env
ids.txt
```

## Instalación en otro servidor

Clone solamente la branch `worker`:

```bash
git clone --branch worker --single-branch \
  https://github.com/bireme/document-extraction.git pdfsum-worker
```

Entre al directorio:

```bash
cd pdfsum-worker
```

Cree la configuración local:

```bash
cp .env.example .env
```

Configure `.env` con los valores reales del ambiente.

Para usar URLs almacenadas en MongoDB:

```dotenv
PDFSUM_INPUT_MODE=url
PDFSUM_INPUT_FOLDER=
```

Para usar una carpeta existente en el servidor de procesamiento:

```dotenv
PDFSUM_INPUT_MODE=folder
PDFSUM_INPUT_FOLDER=MS-all
```

Cree `ids.txt` con los documentos que se procesarán.

Construya la imagen:

```bash
docker compose build
```

Finalmente, ejecute el lote:

```bash
docker compose run --rm pdfsum-worker
```

Para procesar un nuevo lote, actualice `ids.txt` y ejecute nuevamente el mismo comando.

## Persistencia original y publicación BIREME

El comando `run` guarda dos representaciones independientes:

```text
origen (solo lectura) → POST /api/pdfsum → jobs.result (original)
                                             │
                                             ▼
                                      result_mapper.py
                                             │
                                             ▼
                                 resultados BIREME (publicación)
```

`jobs.result` conserva íntegro el valor `result` del sobre HTTP, incluidos sus campos adicionales. El mapper no lo modifica. La publicación no depende del pipeline ni importa módulos de la API.

### Bases y colecciones independientes

| Variable | Valor de `.env.example` | Función |
| --- | --- | --- |
| `PDFSUM_SOURCE_DATABASE` | `FIs_02_converted` | Base de origen |
| `PDFSUM_SOURCE_COLLECTION` | `mis` | Colección consultada, sin escrituras |
| `PDFSUM_JOBS_DATABASE` | `Enrichment_IA` | Base de jobs y originales |
| `PDFSUM_JOBS_COLLECTION` | `document_extraction_jobs` | Identidad única `id + command` |
| `PDFSUM_RESULTS_DATABASE` | `Enrichment_IA` | Base de publicación |
| `PDFSUM_RESULTS_COLLECTION` | `document_abstracts` | Índice único sobre `id` |
| `PDFSUM_RESULT_ID_PREFIX` | `mis-` | Prefijo de publicación; nunca altera consultas ni jobs |
| `PDFSUM_RESULT_FORMAT` | `bireme` | Único formato admitido actualmente |

Todas se transmiten al contenedor y tienen opciones CLI equivalentes: por ejemplo, `--jobs-database` y `--result-id-prefix`. La CLI específica prevalece sobre su variable de entorno. `PDFSUM_MONGODB_URI` sigue disponible exclusivamente en el entorno, sin opción CLI. No guardar `.env` ni credenciales en Git.

Compatibilidad: sin configuración nueva, origen y jobs permanecen en `FIs_02_converted`; `--database` continúa siendo la alternativa para ambos, subordinada a las opciones específicas de cada base. Los resultados usan por defecto `Enrichment_IA.document_abstracts`. El prefijo predeterminado sin configuración es vacío; `.env.example` define explícitamente `mis-`. Copiar el nuevo ejemplo cambia la base de jobs a `Enrichment_IA`: para recuperar jobs históricos configure su base anterior. El worker no migra ni copia jobs automáticamente. Antes de procesar un lote, compruebe que apunta a la colección operacional existente para evitar repetir procesamiento remoto.

Se rechaza cualquier configuración que haga coincidir origen, jobs y publicación. Los índices únicos se verifican al iniciar; si ya hay duplicados, el inicio falla sin borrar documentos. Use un espacio de IDs/prefijos propio de cada origen y una colección de jobs por origen: la identidad operacional continúa siendo solamente `id + command`.

### Ejemplos de documentos

Original operacional, con campos adicionales de fechas, intentos y reserva omitidos:

```json
{
  "id": 75798,
  "command": "run",
  "status": "completed",
  "result": {
    "contract_version": "2.0",
    "idioma_principal": "pt",
    "ai_extracted_abstract": [
      {"lang": "pt", "header": "RESUMO", "text": "Resumo completo.", "keywords": ""}
    ],
    "ai_generated_abstract": null
  },
  "publication": {
    "status": "published",
    "attempts": 1
  }
}
```

Publicación correspondiente, con `meta.source_version` y `meta.revision` omitidos en este ejemplo:

```json
{
  "id": "mis-75798",
  "ab_extracted_ia_pt": "Resumo completo.",
  "meta": {
    "source_id": 75798,
    "source_collection": "mis",
    "source_command": "run",
    "contract_version": "2.0",
    "mapping_version": "1.0"
  }
}
```

Los resúmenes generados se publican en `ab_created_ia_<idioma>`; los extraídos en `ab_extracted_ia_<idioma>`. Los campos están en la raíz y conservan el texto completo, incluidos espacios y saltos de línea. Se omiten valores ausentes, nulos o compuestos exclusivamente por espacios. Un resultado sin resúmenes publica solamente `id` y `meta`, eliminando resúmenes anteriores mediante sustitución completa.

El mapper requiere `contract_version = "2.0"`. Normaliza mayúsculas y espacios del código de idioma; admite `pt`, `es`, `en`, `fr`, `de`, `it` y sus equivalencias `por`, `spa`, `eng`, `fra`/`fre`, `deu`/`ger`, `ita`. Un idioma ausente o fuera de esta lista en un resumen no vacío impide publicar: no se inventa un idioma ni se descarta el texto silenciosamente. La lista explícita evita construir nombres de campos MongoDB a partir de datos arbitrarios.

Para un resumen generado se usa `idioma_principal`. Este campo **no verifica el idioma real del texto generado por el modelo**. El worker no realiza detección de idioma.

Varios resúmenes extraídos que normalicen al mismo idioma producen un error explícito de publicación, incluso si los textos coinciden. El original queda conservado. La función del mapper admite una política `duplicate_policy`, actualmente solo `error`, como punto de extensión; no hay concatenación ni selección automática.

`extract-abstracts` conserva el contrato actual con resúmenes en `result.abstracts`, pero su publicación está desactivada. `transcribe` también conserva su original y nunca convierte transcripciones en resúmenes. Solo `run` escribe en la colección de publicación, evitando colisiones entre comandos del mismo ID.

### Estados y recuperación de publicación

`status=completed` significa que el procesamiento remoto y el guardado original terminaron. Para considerar entregado un `run`, compruebe además `publication.status`:

| Estado | Significado |
| --- | --- |
| `pending` | Original guardado; publicación pendiente |
| `publishing` | Intento reservado durante un máximo de cinco minutos |
| `published` | Documento publicado y confirmado |
| `failed` | Falló la transformación o escritura; original disponible |
| `superseded` | Ya existe una versión más reciente; no se sobrescribe |
| `disabled` | Publicación no aplicable al comando |

El guardado del original y de `publication.pending` es una sola actualización del job. Las escrituras de jobs y publicación usan confirmación `majority`; no se requieren transacciones ni replica set para coordinar ambas colecciones. No hay atomicidad entre colecciones: la recuperación es explícita e idempotente.

Los metadatos de publicación guardan destino, prefijo y origen, fecha de versión del procesamiento y revisión estable. Los reintentos requieren la misma configuración persistida, evitando redirigir silenciosamente un resultado. La versión se compara al sustituir el documento y el índice único protege carreras entre escritores. Una colisión entre revisiones distintas con la misma fecha se registra como fallo; nunca se sobrescribe arbitrariamente. Los relojes de los workers deben estar sincronizados. No elimine manualmente la versión de documentos publicados.

Una caída después de guardar el original se recupera sin OCR ni Ollama. Una caída después de publicar pero antes de confirmar el job repite la misma sustitución. Un claim de publicación abandonado se recupera al vencer su reserva; uno vigente no se roba. Los reintentos de publicación tienen su contador separado y no consumen `--max-attempts`. Cada ejecución intenta una vez cada publicación seleccionada, sin bucles de reintento ilimitados.

Repita el lote original para recuperar sus publicaciones, o recupere todas las pendientes/fallidas y los originales históricos `run` sin estado de publicación:

```bash
docker compose run --rm pdfsum-worker --retry-publications
```

Este modo no consulta el origen ni abre sesión HTTP, no requiere `PDFSUM_SERVER_URL` y no acepta selección de IDs. Usa el destino configurado; si cambió la configuración respecto al job, restáurela antes de reintentar. Los errores de datos requieren corregir su causa explícitamente; repetir el comando no descarta duplicados ni inventa idiomas. Los originales históricos sin `publication` adoptan la configuración vigente en su primer intento. Deben conservar `started_at` o `finished_at`; si faltan ambas fechas, la publicación falla explícitamente porque no puede ordenarse frente a versiones existentes.

La salida del lote distingue `publication_failed`, `publication_pending` y `publication_publishing` de `completed`. Un lote con entregas pendientes o fallidas devuelve código 1; un fallo de configuración o infraestructura devuelve 2.

Los jobs remotos renuevan su reserva cada 30 segundos como máximo durante la llamada HTTP. Solo se recuperan reservas vencidas, manteniendo compatibilidad con jobs antiguos que solo tienen `started_at`. Un token impide que un proceso que perdió su reserva guarde resultados. Una pérdida prolongada de conectividad o una caída después de obtener respuesta remota y antes de persistirla aún puede requerir repetir el procesamiento: la API síncrona no ofrece aquí una garantía de ejecución exactamente una vez.

Se comprueba el tamaño BSON antes de guardar, dejando 64 KiB de margen sobre el límite de 16 MiB. Un original que exceda ese límite se registra como fallo de persistencia; no se trunca ni se publica una copia parcial. No se implementa GridFS. Los errores de publicación no registran URLs ni documentos completos.

### Ejecución y verificación

```bash
cp .env.example .env
# Configure el entorno y prepare ids.txt antes de ejecutar.
docker compose build
docker compose run --rm pdfsum-worker --command run --ids-file /config/ids.txt
docker compose run --rm pdfsum-worker --retry-publications
```

Compose mantiene `extract-abstracts` como comando predeterminado por compatibilidad; para generar publicaciones use explícitamente `--command run`. La imagen incorpora `result_mapper.py` y `result_publication.py`. No se modifica ningún Compose del servidor de procesamiento.

Pruebas locales (MongoDB y HTTP simulados, sin acceso a producción):

```bash
python -m venv .venv
.venv/bin/python -m pip install -r worker_test_requirements.txt
.venv/bin/python -m pytest tests/worker -q
.venv/bin/python -m ruff check pdfsum_worker.py result_mapper.py result_publication.py tests/worker
.venv/bin/python -m compileall -q pdfsum_worker.py result_mapper.py result_publication.py
```
