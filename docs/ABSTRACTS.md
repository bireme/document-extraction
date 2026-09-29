# Resúmenes existentes y generación de respaldo

`run` y `batch` revisan los resúmenes existentes primero. Si queda al menos
uno válido, conservan todos por separado y no llaman al generador. El fallback
determinista de la revisión también cuenta como extracción válida. Solo una
lista final vacía activa la generación.

`extract-abstracts` transcribe y revisa, sin generar. Su salida conserva
`doc_id`, `status`, `source_kind` y usa `ai_extracted_abstract` como lista;
no añade el alias `abstracts`. Una lista vacía significa `not_found`.

`summarize` genera directamente desde un texto: no extrae ni revisa abstracts.

## Contrato 2.0

```json
{
  "doc_id": "documento",
  "contract_version": "2.0",
  "idioma_principal": "es",
  "tipo_documento": "articulo",
  "ai_extracted_abstract": [
    {"lang": "es", "header": "RESUMEN", "text": "Texto presente en el documento.", "keywords": ""}
  ],
  "ai_generated_abstract": null,
  "meta": {"abstract_source": "extracted"}
}
```

En el camino generado, la lista queda vacía y `ai_generated_abstract` contiene
un único texto. Nunca se rellenan ambos. No hay `plantilla` ni `secciones`.
Una respuesta vacía o inválida falla; no se guarda como éxito.
Los idiomas de los abstracts extraídos se conservan individualmente.

`meta.models` identifica los modelos por responsabilidad. Los reports incluyen
`abstracts_extraidos` (cantidad de abstracts), `abstracts_generados` (documentos)
y `generacion_evitada` (documentos). `abstract_source` aparece también en eventos.
El QA del contrato nuevo no exige campos de las plantillas antiguas.

## Modelos y CLI

Defaults de Ollama:

| Responsabilidad | Flag | Configuración | Entorno | Default |
|---|---|---|---|---|
| Revisión | `--abstract-model` | `abstract_model` | `PDFSUM_ABSTRACT_MODEL` | `qwen2.5:7b` |
| Generación | `--summary-model` | `summary_model` | `PDFSUM_SUMMARY_MODEL` | `qwen3:8b` |
| OCR visual | `--vlm-model` | `vlm_model` | `PDFSUM_VLM_MODEL` | `qwen3-vl:8b-instruct` |

Precedencia: CLI → entorno → configuración → default. Se mantienen los
backends Ollama, OpenAI, OpenRouter y Anthropic. Los defaults no restringen
qué modelo puede escoger el usuario. Los identificadores de configuración
se interpretan en el backend seleccionado; al cambiar de proveedor, hay que
ajustarlos o retirar los overrides locales.

`--backend` conserva el proveedor textual compartido. Para separarlos, usa
`--abstract-backend` y `--summary-backend`, las claves `abstract_backend` y
`summary_backend`, o `PDFSUM_ABSTRACT_BACKEND` y `PDFSUM_SUMMARY_BACKEND`.
Dentro de cada nivel, la opción específica prevalece sobre la compartida.
Las API keys siguen fuera del archivo de configuración.

`--model` es un alias legado de `--abstract-model` en `extract-abstracts` y de
`--summary-model` en los demás comandos. Nunca selecciona ambos. Un conflicto
con el argumento específico produce un error. Las claves antiguas `model` y
`cloud_model` solo afectan al flujo estructurado legado; el flujo nuevo avisa
que deben migrarse.

```bash
pdfsum run --in ./input --workspace ./output \
  --abstract-model qwen2.5:7b --summary-model qwen3:8b \
  --vlm-model qwen3-vl:8b-instruct
pdfsum summarize --text ./documento.txt --summary-model qwen3:8b \
  --long-strategy hierarchical --max-chars 42000
pdfsum run --in ./input --workspace ./output \
  --abstract-backend ollama --abstract-model qwen2.5:7b \
  --summary-backend anthropic --summary-model claude-haiku-4-5
```

Estos mismos argumentos pueden pasarse en `command` de Docker Compose.
El deployment externo se actualiza por separado. El worker acepta las mismas
opciones de modelos y generación que `run`.

`doctor` diagnostica revisión, generación y OCR visual por separado. El
preflight del generador ocurre al necesitarlo, no al arrancar el lote. Si
falta el revisor, se registra el motivo y se aplica extracción determinista.
La ausencia del VLM mantiene la degradación existente a Tesseract. En cloud,
el preflight comprueba la API key; no verifica remotamente permisos, cuota ni
existencia del modelo. Un fallo real se registra por documento.

## Documentos largos y ventanas de revisión

`hierarchical` es el default. Los capítulos incluyen sus encabezados; también
se procesa el prefacio y se conserva el cierre del documento. Los capítulos
grandes se dividen en bloques. Las síntesis parciales se reducen en varios
niveles, con entradas limitadas por `max_chars`, hasta producir un texto final.
Si el modelo no comprime, el proceso falla explícitamente en vez de recortar.
Sin capítulos reconocibles se usa `blocks`. No se garantiza que cada dato del
documento aparezca en el abstract final: la cobertura mide el texto procesado.

`excerpt` sigue disponible explícitamente y registra cobertura parcial. No
prioriza un encabezado de abstract. La limpieza previa del texto se conserva
en memoria; el OCR persistido queda intacto.

La revisión usa `abstract_refine_context_chars` para la ventana inicial y
ventanas adicionales desde encabezados posteriores. Las validaciones contra
la transcripción y el fallback conservador siguen vigentes. La detección de
candidatos sin encabezado reconocible fuera de esas ventanas sigue limitada.

## Compatibilidad y reprocesamiento

`SummaryResult`, `summarize_document`, `summarize_pdf`, las plantillas y los
adapters estructurados siguen disponibles como API Python legada. El nuevo
camino usa `DocumentAbstractResult`, `TextGenerator.generate_abstract` y
`generate_document_abstract`. Se reutiliza el transporte HTTP existente; no se
usan `parse_sections()` ni JSON como formato de respuesta del generador.

`read_result` reconoce versiones explícitas, sin convertir artefactos antiguos.
Export, BIBFRAME y verify aceptan ambos contratos. Para resultados nuevos,
LILACS conserva los campos semánticos separados y no inventa título ni
descriptores. BIBFRAME usa los metadatos disponibles del PDF y puede omitir
registros sin título. La edición por secciones sigue siendo una función del
contrato legado. Las rutas HTTP y `summary_url` se conservan, pero los clientes
deben reconocer `contract_version` y los campos nuevos.

Los jobs ya terminados se reutilizan sin cambiar su contrato. Para migrarlos,
ejecuta `batch --reprocess` o arranca `worker --reprocess`: el worker reprocesa
una vez los jobs existentes y después vuelve a su operación normal. `run`
vuelve a procesar los PDFs reutilizando el OCR válido. No se cambia la versión
del cache de OCR ni se fuerza retranscripción por esta migración.

Decisión de implementación: se añadió un camino textual pequeño junto al
estructurado, en vez de cambiar destructivamente `SummaryResult`. El divisor
de bloques compartido corrige la repetición de un buffer previo cuando el
párrafo siguiente ocupa un múltiplo exacto del límite.
