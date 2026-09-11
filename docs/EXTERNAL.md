# Procesamiento de entradas externas

El flujo externo conecta una fuente de entradas, un materializador, un procesador
y un destino de resultados. El motor no conoce MongoDB ni importa `pymongo`.
La primera iteración incluye infraestructura ejecutable con adapters inyectables;
la conexión concreta a MongoDB está pendiente del schema real.

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

## MongoDB: diseño pendiente de schema

MongoDB es el primer provider concreto previsto y tiene un punto de composición
reservado (`--provider mongodb`). **Todavía no conecta ni lee/escribe documentos**.
Informa si falta `pymongo`, la variable `PDFSUM_MONGODB_URI` o el schema. No se ha
añadido esa dependencia porque todavía no se utiliza; al implementar la conexión
se prevé un extra opcional `mongodb`, siguiendo el extra `service` del proyecto.
Los comandos locales y la infraestructura genérica no necesitan esa dependencia.
No se deben guardar URI ni secretos en archivos versionados.

Antes de implementar `MongoInputSource` y `MongoResultStore` se necesita acordar:

- Base de datos, colección de entrada y colección de salida; si son distintas o
  se actualizará expresamente la misma colección.
- Campo/ruta del ID y su tipo, campo/ruta de la URL, campo/ruta del tipo de entrada
  y traducción de sus valores; o un tipo explícito configurado por fuente.
- Filtro de pendientes por comando, orden/límite si aplica y criterio para excluir
  resultados previos.
- Forma de reservar, marcar procesamiento y confirmar, y recuperación/reintento
  de entradas fallidas o interrumpidas.
- Representación del resultado y errores, relación con el ID original, operación
  de escritura (inserción, actualización o upsert) y claves de idempotencia.

Los nombres de opciones de mapeo, filtros y rutas concretas quedan pendientes.
El adapter traducirá documentos a `ExternalInput` y envelopes a las operaciones
acordadas. La selección y escritura permanecerán dentro del adapter, con fuente
y destino independientes; no se actualizarán documentos de entrada por defecto.
Las opciones no secretas podrán ir en `external` y la URI vendrá exclusivamente
de `PDFSUM_MONGODB_URI`. No hay schema MongoDB implícito en los ejemplos anteriores.

## Añadir otro adapter

Implemente `pending(command)` y `save(result)` respetando los contratos de
`pdfsum.external`, y exponga una fábrica `módulo:función`. Si cambia el transporte,
implemente `InputMaterializer` y componga `execute_external` desde Python; la CLI
incluida usa HTTP. No es necesario modificar los cuatro procesadores. Pruebe con
fakes sin red ni bases reales, verificando preservación del objeto ID, políticas
de reserva/reintentos y errores de escritura.
