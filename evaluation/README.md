# Evaluación offline de abstracts

Herramienta experimental para comparar el gold standard con los JSON individuales
que genera `extract-abstracts` en `<workspace>/abstracts/*.json`. Es independiente
del pipeline y **no forma parte del flujo de producción** ni de la CLI `pdfsum`.
Solo usa la biblioteca estándar de Python; no lee el contenido de `report.json`.

## Gold standard

Archivo JSONL UTF-8: un objeto por línea, con `doc_id` de tipo cadena, único y no
vacío, y `abstracts` como lista. Cada abstract requiere `lang` (cadena no vacía)
y `text` (cadena, que puede estar vacía). Un documento puede tener cero, uno o
varios abstracts, incluso del mismo idioma:

```jsonl
{"doc_id":"ejemplo-001","abstracts":[{"lang":"es","text":"Texto correcto del resumen."}]}
{"doc_id":"ejemplo-002","abstracts":[]}
```

`reference.example.jsonl` contiene datos ficticios. No se incluye un gold standard
real de producción. Las líneas vacías se consideran JSON inválido.

## Ejecución

Desde la raíz del repositorio:

```bash
python evaluation/evaluate_abstracts.py \
  --reference evaluation/reference.jsonl \
  --predictions /output/abstracts \
  --out evaluation/results/evaluation.json
```

Se crea el directorio de salida si hace falta; un informe existente se sobrescribe.
Los thresholds predeterminados son **0.80, 0.85, 0.90, 0.92, 0.95, 0.97, 0.98 y 0.99**.
Para cambiarlos, añada, por ejemplo, `--thresholds 0.85 0.95`. Deben ser números
finitos entre 0 y 1, incluidos los extremos; los repetidos se evalúan una sola vez.

## Comparación y clasificaciones

La normalización aplica Unicode NFC, minúsculas, sustitución de saltos de línea
y cualquier secuencia de whitespace por un espacio, y trim. Conserva acentos y
puntuación. No usa stemming, traducción ni embeddings.

Sobre los textos normalizados se calcula:

```text
similarity = 1 - Levenshtein(reference, prediction) / max(len(reference), len(prediction))
```

Inserciones, eliminaciones y sustituciones cuestan 1; se comparan caracteres
Unicode de Python. Dos textos vacíos tienen similarity 1.0; uno solo vacío, 0.0.
El algoritmo usa tiempo O(n*m) y memoria O(min(n,m)).

Se recorren los abstracts en el orden del gold standard. Para cada uno se escoge
la predicción disponible con mayor similarity y el mismo `lang` exacto. En caso
de empate gana el índice menor de la lista de predicciones. Cada predicción se
usa una sola vez; el matching se calcula antes de aplicar los thresholds.

- **TP**: par con similarity mayor o igual al threshold.
- **FN**: abstract esperado sin candidato del mismo idioma.
- **TEXT_MISMATCH**: par con similarity inferior al threshold.
- **FP**: predicción extra sin abstract esperado correspondiente.
- **TN**: documento presente en ambas entradas y con ambas listas vacías.

En las métricas agregadas, **cada TEXT_MISMATCH aporta un FP y un FN** y se
mantiene además su contador propio. El detalle conserva siempre TEXT_MISMATCH.
Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = 2*TP/(2*TP+FP+FN).
Si el denominador es cero, el resultado es 0.0. TN se cuenta por documento;
los demás resultados se cuentan por abstract.

## Archivos ausentes, extras y validación

Se evalúa la unión de los `doc_id` de ambas entradas, usando el campo del JSON,
no el nombre del archivo. Un documento sin archivo de predicción genera FN por
cada abstract esperado. Uno ajeno al gold genera FP por cada abstract previsto.
Ambos casos quedan identificados mediante `reference_present` y
`prediction_present`. Si su lista está vacía, no aporta TP, FP, FN ni TN, pero
permanece en el detalle. Un archivo ausente nunca demuestra un TN.

Se leen únicamente los `*.json` del directorio indicado, sin recursión, excluyendo
`report.json`. Los campos `status`, `header` y `keywords` no intervienen: la lista
`abstracts` es la fuente del contenido. `source_kind` se conserva si está disponible.
Se rechazan JSON inválidos, campos obligatorios ausentes o de tipo incorrecto,
identificadores duplicados en cualquiera de las entradas y directorios inexistentes.
Los errores impiden generar un informe parcial y terminan con código distinto de cero.

## Informe y limitaciones

El JSON incluye rutas de entrada, detalle por documento, índices de los abstracts
(base cero), idioma, similarity, clasificación por threshold y predicciones extras.
`matched_abstracts` incluye también los FN, con índice previsto y similarity `null`.
Los fragmentos diagnósticos se limitan a 200 caracteres normalizados por texto.

Las estadísticas incluyen todos los pares del matching, también TEXT_MISMATCH:
count, mean, median, min, max y percentiles p10, p25, p75 y p90. Los percentiles
usan interpolación lineal en la posición `(count - 1) * p`. Sin pares, count es
cero y las demás estadísticas son `null`.

El matching es guloso y depende del orden; no optimiza globalmente la asignación.
No hay matching semántico ni equivalencia entre etiquetas de idioma. La distancia
puede ser costosa para textos largos y penaliza cambios legítimos de redacción.
La calidad del gold standard y su cobertura condicionan los resultados: incluir
predicciones ajenas al gold aumenta FP. No se evalúan headers ni keywords, ni se
valida la coherencia entre `status` y la lista de abstracts.
