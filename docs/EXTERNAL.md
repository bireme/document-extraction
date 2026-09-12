# Procesamiento de entradas externas

El flujo externo conecta una fuente de entradas, un materializador, un procesador
y un destino de resultados. El motor no conoce MongoDB ni importa `pymongo`.
Incluye adapters inyectables y un provider MongoDB con selección explícita por ID,
fuente de solo lectura y una colección operacional separada.

## Comandos y resultados

| Comando | `input_type` | Resultado principal externo |
| --- | --- | --- |
| `pdfsum external run` | `pdf` | JSON final de `summaries/`, incluyendo QA |
| `pdfsum external extract-abstracts` | `pdf` | JSON principal de `abstracts/` |
| `pdfsum external transcribe` | `pdf` | Texto de la transcripción canónica en `ocr/` |
| `pdfsum external summarize` | `text` | JSON de `summarize_document`, equivalente a `summarize` local |

El executor rechaza tipos incompatibles antes de descargar. `summarize` recibe
texto ya transcrito: no ejecuta OCR ni convierte PDF implícitamente.

`ExternalInput` conserva `id`, `input_type` y `url`. `ExternalResult` conserva el
mismo objeto `id`, el comando, el estado `completed`/`failed` y el resultado propio
del comando. Los fallos incluyen fase, tipo de excepción y mensaje seguro.
Estos tipos son contratos Python; **no definen documentos MongoDB**.
Los valores internos `doc_id` siguen siendo identificadores locales seguros,
como exige el workspace. La identidad externa se conserva en el envelope, sin
convertir `ObjectId` ni forzarlo dentro de un JSON del dominio.

## Reutilización del procesamiento

`LocalInputProcessor` llama a `run_batch_pdfs`, `extract_abstracts_from_pdfs` y
`transcribe_pdfs` con una lista explícita de una ruta. Los runners locales siguen
seleccionando los archivos del directorio cuando no reciben esa lista. El resumen
de texto usa directamente `summarize_document`, igual que la CLI local.
No se duplican OCR, extracción determinista, revisión LLM, fallback, limpieza de
texto, QA ni observabilidad. Cada invocación PDF mantiene su reporte normal;
`report.json` refleja la última entrada procesada por ese runner y `events.jsonl`
conserva el historial. El executor devuelve solamente contadores, sin acumular los
resultados completos del lote.

## Configuración y ejecución

Se usa el cargador habitual de `.pdfsum-config.json` (directorio actual, después
home). La clave `external` es un objeto de configuración para el provider:

```json
{
  "external": {
    "provider": "mi_integracion:fabrica",
    "download_timeout": 30,
    "max_download_bytes": 100000000
  }
}
```

`mi_integracion:fabrica` representa una función de un módulo Python instalado de
confianza. No viene incluida: la implementación devuelve `(InputSource,
ResultStore)` y recibe el objeto `external`. Puede recibir opciones propias de
conexión y mapeo sin introducirlas en el motor. Esta fábrica permite ejecutar hoy
el flujo con una fuente/destino propios. Los tests incluyen fakes completos.

```bash
pdfsum external run --workspace ./data --provider mi_integracion:fabrica
pdfsum external extract-abstracts --workspace ./data --provider mi_integracion:fabrica
pdfsum external transcribe --workspace ./data --provider mi_integracion:fabrica
pdfsum external summarize --workspace ./data --provider mi_integracion:fabrica
```

`--provider` prevalece sobre `external.provider`. `--download-timeout` prevalece
sobre `external.download_timeout`. Se mantienen la fábrica de LLM y sus opciones
`--backend`, `--model`, variables de entorno y configuración habituales.
`--lang` controla OCR para los comandos PDF e idioma del resumen para texto;
`--pages` describe las páginas del texto en `summarize`; `--long-strategy` se aplica
a `run`. `--fake` sustituye OCR y LLM; `--dry-run` sustituye solamente LLM.
**Ambas opciones siguen descargando y persistiendo resultados en el provider**.

El materializador HTTP exige timeout y limita el tamaño, escribe por streaming,
rechaza respuestas HTTP fallidas, vacías, incompletas y tipos MIME incompatibles.
Para PDF verifica cabecera y marcador final; es una comprobación preliminar, no
una validación estructural completa. Para texto exige UTF-8 estricto cuando no
hay charset y admite UTF-16 declarado explícitamente; normaliza a UTF-8 y rechaza
controles binarios, codificaciones desconocidas y contenido PDF. No deduce el tipo
de la extensión de la URL. Admite HTTP/HTTPS y rechaza credenciales en la autoridad
de la URL; las URLs con query strings se usan para descargar sin registrarse.
La política SSRF rechaza nombres locales y direcciones IPv4/IPv6 no globales,
multicast y reservadas. Valida todas las IP resueltas antes de crear el socket y
conecta directamente a una IP numérica validada, sin segunda resolución DNS.
Conserva Host, SNI y verificación TLS; repite la política en cada redirect y
mantiene los límites de urllib. Este transporte desactiva proxies automáticos.

## Artefactos e identidad local

Cada intento usa un nombre con hash del identificador y un UUID, separado del ID
original. No hay interpolación del ID bruto en rutas. Los intentos diferentes no
comparten nombres ni sobrescriben resultados anteriores. Esto evita colisiones,
pero la reutilización de caché entre intentos externos queda a futuro: la política
de no reprocesamiento corresponde al provider.

Sin `--keep-artifacts`, se elimina la descarga de `workspace/downloads/` y el JSON
principal que esta entrada creó en `summaries/` o `abstracts/`. También se limpian
parciales tras errores recuperables y fallos del store. No se eliminan OCR,
metadatos OCR, logs, `events.jsonl`, `infrastructure.jsonl` ni `report.json`.
Para `transcribe`, su texto principal permanece en `ocr/` porque es el propio
artefacto OCR; no se crea otra copia temporal de esa transcripción.

Con `--keep-artifacts` se conservan las descargas válidas y los resultados locales
en esas ubicaciones canónicas. Las descargas inválidas o incompletas se descartan
siempre. La limpieza enumera rutas de esta entrada y no borra árboles de
directorios. El JSON principal es el único resultado que se envía externamente,
o el texto en `transcribe`; nunca se envían OCR auxiliar, logs o reportes completos.

## Errores, observabilidad e idempotencia

Los fallos de validación, descarga y procesamiento se entregan al store con su ID
original. Un fallo de persistencia detiene el lote y lanza `ResultStoreError`, que
retiene `id` y el envelope completo para el llamador Python. No se intenta guardar
el error en el mismo store que acaba de fallar. La CLI informa el fallo sin
imprimir el resultado ni el mensaje original del proveedor. Los códigos de salida
son 0 (completados), 1 (entradas fallidas persistidas) y 2 (fallo de ejecución o
configuración). Si falla la limpieza se registra el incidente y se lanza
`ArtifactCleanupError` con el ID original; se intenta limpiar el resto de archivos
sin ocultar una excepción de persistencia que ya estuviera en curso.

Los eventos externos incluyen comando, fase, tipo de error y
`external_id_reference`, la referencia segura del intento que también identifica
sus artefactos. No serializan el ID opaco ni el resultado completo. Los mensajes
de error de terceros se omiten por privacidad: podrían contener URLs, tokens,
prompts o transcripciones. Los runners PDF reciben un formateador seguro solo en
este flujo; el comportamiento local permanece igual. Los adapters propios deben
seguir esa misma política y evitar registrar secretos en sus logs internos.

`InputSource.pending(command)` selecciona y, cuando corresponda, reserva entradas.
`ResultStore.save(result)` persiste idempotentemente y confirma la reserva según
la política del provider. Se puede compartir contexto privado entre fuente y
store para gestionar claims sin cambiar los contratos del procesamiento. El
executor es secuencial y no implementa locks ni asume estados en la base. El
provider debe definir exclusión de éxitos previos, recuperación de reservas,
reintentos y la identidad de una ejecución (por ejemplo, comando y versión del
recurso, si así se decide). No se promete ejecución exactamente una vez.

## MongoDB real

Instalación opcional (los comandos locales y otros providers no la necesitan):

```bash
pip install '.[mongodb]'
```

La URI se obtiene **exclusivamente** de `PDFSUM_MONGODB_URI`. No se admite una
opción de URI en la CLI ni una URI en la configuración. No la guarde en archivos
versionados ni la incluya en comandos compartidos. Los nombres no secretos se
configuran dentro de `external`:

```json
{
  "external": {
    "provider": "mongodb",
    "database": "FIs_02_converted",
    "source_collection": "mis",
    "jobs_collection": "document_extraction_jobs"
  }
}
```

`--database`, `--source-collection` y `--jobs-collection` prevalecen sobre esas
claves. Los valores del ejemplo son los predeterminados. Se rechaza usar como
colección de jobs la fuente o `mis`. **mis permanece intacta**: solo se ejecutan
lecturas por el campo funcional `id`; no se usa `_id` como identificador, no se
actualizan documentos y no se crean índices en la fuente.

Cada lanzamiento MongoDB exige `--ids` o `--ids-file`, mutuamente excluyentes.
No toma IDs guardados en la configuración ni selecciona toda la colección.
Los IDs son **enteros**, como `mis.id`: los tokens se validan y convierten a
enteros BSON de 64 bits antes de conectar. Se eliminan duplicados conservando el
orden; `0079665` y `79665` representan el mismo entero. Un archivo UTF-8 puede
contener un ID por línea o varios separados por espacios. Un archivo vacío,
inaccesible o con un token que no sea entero se rechaza antes de conectar.

Estos son ejemplos de ejecución; escriben jobs y no constituyen una prueba de
solo lectura. Incluso `--fake` y `--dry-run` descargan y escriben datos:

```bash
pdfsum external run --provider mongodb --workspace ./data --ids 79665 79662 79667
pdfsum external extract-abstracts --provider mongodb --workspace ./data --ids-file ids.txt
pdfsum external transcribe --provider mongodb --workspace ./data --ids 79665
```

### Selección del PDF

Para `run`, `extract-abstracts` y `transcribe` se leen todos los valores
`electronic_address[*]._u`. Solo se aceptan URLs explícitas HTTP/HTTPS cuyo path
termine en `.pdf` (sin distinguir mayúsculas), con query string opcional.
Se prefieren HTTPS y, entre candidatos equivalentes, el orden original.
Se conserva la URL exacta: no se reparan esquemas ausentes, espacios, controles,
puertos inválidos, `.pdf.`, `.pd` ni escapes malformados. No se siguen DOI o HTML
para descubrir PDFs, ni se aceptan EPUB, imágenes o YouTube como recurso.

La extensión solo selecciona el candidato; después, HTTPMaterializer aplica
SSRF, límites y validación de contenido. Si la URL seleccionada falla, el job
falla; no se prueban otros enlaces automáticamente. No se debilita la política
para direcciones de redes internas.

`pdfsum external summarize --provider mongodb` informa que `mis` no tiene una
fuente identificada de texto transcrito y termina antes de conectar o crear jobs.
El comando local y el soporte genérico de `summarize` continúan disponibles.

### Jobs, reserva y resultados

La primera iteración crea, si falta, la colección operacional mediante su índice
único `id_command_unico` sobre `(id, command)`. Cada ID explícito se prepara con
`update_one(..., {"$setOnInsert": ...}, upsert=True)` en estado `pending`.
Un índice existente incompatible o datos duplicados producen un error de
infraestructura; el adapter no modifica ni elimina esos datos para corregirlo.

La reclamación usa `find_one_and_update` sin upsert, con el filtro:

```python
{"id": 79665, "command": "run", "status": {"$in": ["pending", "failed"]}}
```

La misma operación atómica establece `processing`, un `claim_token` aleatorio,
`started_at` y `updated_at`, e incrementa `attempts`. Solo quien obtiene el
documento puede procesarlo. El guardado exige ese token y el estado correspondiente;
un intento anterior no puede sobrescribir una reserva nueva. Las escrituras de
jobs usan confirmación mayoritaria, incluso si la URI solicita `w=0`.

Los jobs incluyen `id` numérico, `command`, `status`, `created_at`, `updated_at`,
`started_at`, `finished_at` al finalizar, `attempts` y `claim_token`. Las fechas
se escriben en UTC. `completed` guarda exclusivamente `result`: JSON principal
de `run` o `extract-abstracts`, o texto principal de `transcribe`. `failed` guarda
un error estructurado con `phase`, `code` y `message` seguro. No se almacenan la
URI, la URL de descarga ni mensajes originales de excepciones en esos errores.
No se copian OCR auxiliar, logs, `report.json` o `events.jsonl` completos.

Los jobs `completed` se omiten aunque se vuelvan a indicar sus IDs. Los `failed`
son elegibles en un nuevo lanzamiento explícito; se reemplazan el error anterior
y los tiempos del intento por los del nuevo intento. No hay reintentos infinitos
ni reintentos internos del procesamiento. El estado `processing` **no caduca**:
si un proceso se interrumpe, la recuperación debe decidirse operativamente tras
verificar que el dueño anterior ya no trabaja. No hay recuperación automática ni
promesa de ejecución exactamente una vez. Se conserva solo el último intento,
además de su contador; no se mantiene un historial completo en MongoDB.

ID inexistente, ausencia de `electronic_address` y ausencia de PDF generan
`failed` con códigos `id_inexistente`, `sin_recurso` y `sin_pdf`, respectivamente,
y el lote continúa. Estos fallos se persisten en la fuente/store compartida antes
de entregar entradas al executor; la CLI suma `selection_failures` a los fallos
del procesamiento. Los llamadores Python que compongan el adapter directamente
deben sumar ese contador si necesitan el total del lote.

Errores HTTP y de procesamiento siguen el flujo genérico y fallan solo ese job.
Errores de lectura, índice, reclamación o persistencia en MongoDB son de
infraestructura y detienen el lote con un mensaje sanitizado. El resultado debe
caber en un documento BSON (límite MongoDB de 16 MiB); no se implementa GridFS ni
fragmentación, y superar ese límite es un fallo de persistencia. La búsqueda por
`mis.id` aprovecha los índices ya existentes; este adapter no crea uno en `mis`.
`--keep-artifacts` conserva exactamente su comportamiento previo.

Los tests sustituyen el driver, las colecciones, DNS y sockets; no necesitan un
MongoDB real. La validación operativa con una instancia real queda separada de
estos tests y requiere confirmar el comando y sus escrituras antes de ejecutarlo.

## Añadir otro adapter

Implemente `pending(command)` y `save(result)` respetando los contratos de
`pdfsum.external`, y exponga una fábrica `módulo:función`. Si cambia el transporte,
implemente `InputMaterializer` y componga `execute_external` desde Python; la CLI
incluida usa HTTP. No es necesario modificar los cuatro procesadores. Pruebe con
fakes sin red ni bases reales, verificando preservación del objeto ID, políticas
de reserva/reintentos y errores de escritura.
