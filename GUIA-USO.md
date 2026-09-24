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
| Extraer resúmenes existentes | `pdfsum extract-abstracts --in ./pdfs --workspace ./data` |
| Servicio (API + worker) | `PDFSUM_API_TOKEN=... pdfsum api --workspace ./service_ws` + `pdfsum worker --workspace ./service_ws` |
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
  La caché está **versionada**: si el PDF cambia (hash) o mejora el
  pipeline OCR, se re-transcribe sola. `--retranscribe` fuerza re-OCR.
  Para regenerar desde cero, borra el workspace.
- **Calidad de transcripción medible:** junto a cada `ocr/<doc_id>.txt`
  se escribe `ocr/<doc_id>.meta.json` (fuente y confianza OCR por página,
  páginas VLM/vacías). Antes de resumir se ejecutan gates de transcript
  (caracteres basura, señal de idioma, páginas vacías, confianza baja);
  el veredicto va en `_qa.transcript` de cada resumen y en el bloque
  `transcription_quality` de `report.json` (versión 3.1). Un transcript
  degradado NO bloquea el resumen: queda marcado para revisión humana.
  Transcripts de cachés antiguas aparecen con warning `legacy_cache`.
- **Tiempos:** los nativos se extraen al instante; los escaneados se resuelven
  con OCR por región (Tesseract o VLM). Un folleto escaneado de pocas páginas
  puede tardar ~1–3 min con el VLM local; re-ejecutar no lo repite (cacheado).
- **Nativos** se extraen directo; **escaneados** pasan por OCR con segmentación
  por columnas y fallback al modelo de visión en páginas difíciles.
- **VLM verificado:** la salida del modelo de visión se verifica antes de
  aceptarse (anti-alucinación: solape con lo que leyó Tesseract, idioma,
  cháchara); si se rechaza dos veces, la región degrada al texto
  Tesseract y queda marcada (gate `vlm_rechazado`, evento y meta) para
  revisión humana. Nunca entra texto VLM sin verificar ni vacíos mudos.
- **Preprocesado OCR:** las páginas escaneadas se renderizan en gris sin
  compresión y pasan por autocontraste + enderezado automático (deskew)
  antes del OCR — cadena aceptada por benchmark (+5% palabras, −13%
  tiempo; `benchmarks/RESULTADOS-F18.md`). Regiones con tinta pero sin
  texto legible (figuras/tablas) se marcan con aviso si no hay VLM.
- **Mixtos:** la decisión nativo/OCR es **por página** — un libro nativo con
  anexos escaneados ya no pierde esas páginas: solo ellas pasan por OCR
  (`source_kind: mixto`, fuente por página en `ocr/<doc_id>.meta.json`).
- **Texto crudo vs limpio:** `ocr/*.txt` conserva el texto verbatim del
  origen (auditable). Antes de resumir se aplica en memoria una limpieza
  (des-hifenización de cortes de línea, encabezados/pies repetidos,
  números de página). En `run`, los abstracts se extraen y revisan sobre la
  transcripción cruda antes de limpiar el texto para generar el resumen.
- **Idiomas:** el resumen sale en el idioma del documento; los abstracts de
  origen multilingües se preservan verbatim.
- Si falta Ollama/modelo, los comandos se detienen con un mensaje claro de qué
  instalar (ver también `pdfsum doctor`).

### Extraer resúmenes existentes

`extract-abstracts` transcribe los PDFs y recupera los resúmenes ya presentes
en los documentos, sin generar un resumen nuevo del artículo. La extracción
determinística aporta candidatos; el LLM localiza y refina los límites usando
la transcripción como fuente de verdad. Los candidatos con contaminación
editorial evidente se excluyen del prompt, pero se conserva la transcripción.
Puede recuperar texto anterior al
encabezado o ausente de los candidatos. La validación busca respaldo en todo
el contexto enviado, con preferencia por coincidencias contiguas. Admite
espacios, guiones de fin de línea y correcciones OCR limitadas; rechaza cifras
alteradas, traducciones, paráfrasis y contenido nuevo.

Cada entrada del JSON se busca independientemente en todo el contexto: el
orden de respuesta no limita la búsqueda. Se rechazan spans duplicados o
superpuestos, incluso entre idiomas distintos o entre las dos llamadas.
Los resultados se ordenan por su posición real en la transcripción.

También admite spans ordenados separados por bloques editoriales cortos, con
señales de layout verificables. Cada laguna se valida: no basta con encontrar
las palabras en distintas partes del documento. No se permite quitar prosa
interna ni invertir frases. El texto posterior al span no tiene que formar
parte del resumen. Las introducciones estructuradas con secciones de métodos
siguen siendo válidas; un encabezado de resumen no legitima el cuerpo del artículo.

`abstract_refine_context_chars` limita los caracteres iniciales disponibles
para la revisión (20 000 por defecto); no permite recuperar contenido fuera
de esa ventana. Se usa el mismo backend/modelo configurado, sin dependencias
adicionales.

Tras una respuesta válida, incluso vacía, se comprueba la completitud dentro
de esa ventana. La heurística exige un marcador de palabras clave al inicio
de una línea, antes del primer cuerpo de artículo reconocido, y un bloque
inmediato de 40 a 6000 caracteres, al menos ocho palabras y puntuación final.
Usa límites de párrafo/encabezado, descarta contaminación editorial y exige
compatibilidad entre el idioma del marcador, las señales léxicas del bloque
y un encabezado de resumen presente en el contexto, aunque esté desplazado.
No compara los idiomas de los candidatos determinísticos ni extrae ese bloque
automáticamente. Un marcador aislado o dentro del cuerpo no basta.

Si queda evidencia sin un span validado del mismo idioma, se hace una sola
llamada complementaria. El prompt identifica los resúmenes ya validados y
pide únicamente los ausentes, sin modificar los anteriores, resumir el cuerpo,
traducir ni parafrasear. La respuesta pasa por la misma validación extractiva.
Si falla la llamada, el JSON o la validación, se conserva la primera revisión;
si la evidencia sigue pendiente, el resultado se registra como incompleto.
No se inicia otro ciclo ni se promueve un candidato sospechoso como reemplazo.

Esta comprobación detecta evidencia de otro resumen, no certifica que cada
resumen esté íntegro ni que todos los existentes hayan sido encontrados.
Puede omitir bloques sin palabras clave, sin encabezado compatible, con idioma
incierto o con layout que no satisfaga las señales conservadoras. No amplía
los permisos para omitir prosa interna ni modifica los límites de ruido editorial.

Si falla la revisión, el fallback conserva candidatos sin contaminación
editorial evidente y descarta los sospechosos (por ejemplo, rótulo inicial
de artículo original o referencia editorial con año/volumen). Esto no
certifica la calidad de los candidatos conservados. El fallo no es fatal para
el documento. Sin LLM se mantiene la extracción determinística sin revisión.

```bash
pdfsum extract-abstracts --in ./pdfs --workspace ./data
```

Los resultados se guardan en `abstracts/<doc_id>.json`.

### Observabilidad de `extract-abstracts`

El comando reutiliza `EventLog` y la escritura atómica de reportes de `run`.
Los eventos se añaden a `events.jsonl` junto a `report.json`, en `--logs-dir`
o, si no se configura, en `summaries/` dentro del workspace. Cada lote tiene
su propio `run_id`; el reporte se actualiza después de cada documento.

Los eventos `document_started`, `phase_started`, `phase_completed`,
`phase_failed` y `document_completed` permiten seguir la transcripción,
extracción determinística, preparación de la revisión, llamada al LLM,
validación y resultado. `abstract_refine_started` y `abstract_refine_completed`
registran backend, modelo, candidatos y resultado. `context_chars` mide los
caracteres de la transcripción recortada que se envía; `prompt_chars` mide el
prompt completo, incluidos instrucciones y candidatos. No son conteos de tokens.
Los tiempos `seconds` usan un reloj monotónico. Si falla la revisión,
`abstract_refine_fallback` incluye `error_type`, `error` con el mensaje de la
excepción y `failure_phase`. El fallback aplica el filtro conservador descrito
arriba. Los eventos de validación incluyen cobertura, método, número de spans,
lagunas, tokens/caracteres ignorados y motivos de aceptación de las lagunas.
`abstract_refine_validation` incluye `abstract_index` (desde cero, dentro de
cada respuesta), `abstract_lang`, `abstract_header`, `validation_attempt`
(1 o 2), `span_start` y `span_end`, tanto al aceptar como al rechazar una
entrada. Solo se registran idiomas/encabezados admitidos por el contrato;
los inválidos quedan vacíos. Los offsets corresponden al contexto normalizado
(NFC, sin guiones de fin de línea y con espacios horizontales compactados),
con extremo final exclusivo; son `null` si no se localizó el span. Los fallos
del JSON completo no tienen índice de entrada. No se registra el abstract.

Cada documento de `report.json` incluye `abstract_extraction` con
`refinement_attempted`, `refinement_succeeded`, `fallback`, `fallback_reason`,
`failure_phase`, `error_type`, `candidate_count`, `final_count` y
`discarded_candidates`. Los comandos `run` y `batch` también conservan ese
bloque en `meta` del resultado; el cache de `batch` lo preserva. La fase permite
distinguir errores operativos de la llamada al LLM de fallos de validación.
Una ejecución exitosa del pipeline no implica una revisión exitosa del abstract.

El mismo bloque incluye `completion_checked`, `completion_succeeded`,
`completion_retry_attempted`, `completion_retry_succeeded`,
`completion_retry_error_type`, `completion_retry_failure_phase` y
`missing_abstract_evidence`. El evento `abstract_refine_completion` publica
estos campos sin contenido textual. La evidencia pendiente contiene solo
`lang`, `span_start` y `span_end` en el contexto normalizado. Las fases del
intento adicional son `llamada_complementaria` y `validacion_complementaria`.
`completion_succeeded` significa que no queda evidencia detectada pendiente,
no una garantía de exhaustividad. Sin revisión válida, `completion_checked`
es falso. `completion_retry_succeeded` solo es verdadero si se intentó el
complemento y resolvió toda la evidencia. Una respuesta complementaria vacía
puede dejarlo falso sin error operativo. `refinement_succeeded=true` junto a
`completion_succeeded=false` y `completion_checked=true` indica revisión
válida pero incompleta; no activa el fallback de la primera llamada.

El reporte y la salida de la CLI incluyen documentos con revisión LLM exitosa,
fallback determinístico y ningún abstract. Una revisión válida que devuelve
una lista vacía y no recupera resúmenes en el complemento cuenta como exitosa
y como documento sin abstract, con el diagnóstico de completitud aparte; un fallback
sin candidatos también cuenta como documento sin abstract. `accepted_count`
cuenta abstracts aceptados por la revisión; `final_count` cuenta los que quedan
tras aplicar el fallback, si hizo falta. Los modos `--fake` y `--dry-run`
registran backend `fake`, sin atribuirles un modelo remoto.

Los logs no guardan la transcripción, el prompt ni la respuesta completa del
LLM. El reporte operativo tampoco duplica los abstracts: su contenido sigue
en `abstracts/<doc_id>.json`, cuyo formato no cambia. El mensaje de excepción
se conserva para diagnosticar los fallos; no se añade un volcado de contenido.
