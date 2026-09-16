# PDFSum Worker

Worker de orquestación para procesamiento remoto de documentos con PDFSum.

El worker obtiene la información de los documentos desde MongoDB, selecciona la URL del PDF, envía el documento al servidor remoto de procesamiento y persiste el resultado en MongoDB.

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

## Responsabilidades

El worker se encarga de:

* leer registros de la colección `mis`;
* seleccionar una URL PDF desde `electronic_address`;
* crear y controlar jobs en `document_extraction_jobs`;
* llamar al endpoint `POST /api/pdfsum`;
* persistir resultados y fallos en MongoDB;
* controlar intentos de procesamiento;
* recuperar jobs abandonados en estado `processing`.

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

Edite `.env` y configure las variables:

```dotenv
PDFSUM_MONGODB_URI=mongodb://usuario:senha@mongodb.example:27017/
PDFSUM_SERVER_URL=http://servidor-pdfsum:8766
```

### `PDFSUM_MONGODB_URI`

URI de conexión al MongoDB utilizado por el worker.

El valor real no debe almacenarse en Git.

### `PDFSUM_SERVER_URL`

URL base del servidor que ejecuta PDFSum Processing API.

El worker agrega automáticamente `/api/pdfsum` cuando la URL configurada no contiene el endpoint completo.

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

## MongoDB

Por defecto, el worker utiliza:

```text
database: FIs_02_converted
colección fuente: mis
colección de jobs: document_extraction_jobs
```

La colección `mis` se utiliza solamente como fuente de información.

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

Por defecto, un job se considera abandonado después de 60 minutos.

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

