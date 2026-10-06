# Reutilización del TSV en OCR híbrido

Cada región ejecuta Tesseract una sola vez con `--psm 1 tsv`. Si el routing
acepta Tesseract, se reconstruye el texto del TSV. Sin VLM disponible también
se reutiliza ese texto. Los umbrales, las palabras de contraste del VLM, sus
dos intentos como máximo y la degradación tras rechazo no cambian.

El parser conserva Unicode, puntuación y comillas literales. Agrupa por
página, bloque, párrafo y línea, en orden numérico, manteniendo el orden de
las palabras dentro de cada línea. Une palabras con un espacio y líneas con
un salto; no reproduce líneas vacías ni el salto final del renderer de texto.
Omite texto vacío y filas con confianza negativa o no numérica, igual que el
fallback anterior. No hay garantía de identidad byte a byte con texto puro.
Los metadatos derivados del texto, como `chars`, reflejan esa normalización;
no cambia su contrato ni la lógica de QA.

## Benchmark manual

Desde el checkout con sus dependencias y poppler/Tesseract instalados:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/benchmark_ocr_workers.py \
  --compare-tsv --workers 1 3 --warmup --repeats 3 \
  --out /tmp/ocr-tsv-resultados documentos/*.pdf
```

El modo `dos_llamadas` usa una subclase exclusiva del benchmark para repetir
la llamada de texto en las mismas rutas que la implementación anterior.
El modo `tsv` usa el adaptador de producción. No se requiere GPU. Para medir
además el fallback real, añadir `--vlm-model qwen3-vl:8b-instruct` y mantener
el mismo `--vlm-workers` en ambas variantes.

`segundos` mide la transcripción completa del documento, incluyendo extracción
nativa, render, segmentación y OCR, sin resumen ni caché de pdfsum. El JSON
registra llamadas TSV/texto, total de llamadas, regiones y hashes exactos y
normalizados por whitespace. Los TXT permiten revisar diferencias de líneas.
`palabras_iguales_referencia` compara con la primera ejecución del documento;
los campos de equivalencia secuencial comparan dentro de cada modo. Usar
`--workers 1 3` para que la primera referencia sea secuencial. El orden de
los modos se alterna entre repeticiones. El tiempo de la referencia incluye
el pequeño coste de reconstruir y descartar el TSV antes de obtener texto.

Los contadores existen solo en el benchmark: no se añaden campos a eventos
ni a `report.json`. No cambian CLI de pdfsum, configuración, dependencias,
variables de entorno, modelos, Dockerfile ni Compose. Hay que reconstruir o
actualizar la imagen desplegada para incorporar el código nuevo.

Validar también con documentos escaneados, mixtos y nativos representativos;
la igualdad de palabras no garantiza igualdad de estructura visual. Las
pruebas unitarias no dependen de Tesseract real ni de GPU.

## Medición local de referencia

PDF sintético escaneado de tres páginas con portugués, español e inglés,
72 regiones, `por+eng+spa`, sin VLM, una repetición sin calentamiento:

| Workers | Dos llamadas | Reutilizar TSV | Llamadas antes → después |
| --- | --- | --- | --- |
| 1 | 62,86 s | 32,29 s | 144 → 72 |
| 3 | 21,74 s | 12,51 s | 144 → 72 |

Reducción observada: 48,6 % y 42,4 %, respectivamente. Las cuatro ejecuciones
produjeron la misma secuencia de palabras; el hash exacto difiere entre modos
por los saltos finales de las regiones. Dentro de cada modo, texto y detalles
fueron idénticos con 1 y 3 workers. Es una medición exploratoria local, con
validaciones ejecutándose en paralelo; repetir sin otra carga con documentos
representativos antes de extrapolar tiempos al servidor.

Con Tesseract 5.5.1 también se verificó una región sintética de alta confianza
(96,38; 85 palabras): routing Tesseract, una sola llamada y la misma secuencia
de palabras que la salida tradicional. `make check` completó 319 pruebas:
314 exitosas, ninguna fallida y 5 omitidas por opciones/dependencias externas.
La suite necesitó ejecutarse fuera del sandbox para las pruebas de API local.
