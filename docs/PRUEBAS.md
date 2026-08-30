# Arquitectura de pruebas

La suite conserva `unittest` y se organiza de forma incremental. Los tests
históricos permanecen en `tests/`; el ejecutor los clasifica sin una mudanza
masiva, mientras que las suites nuevas de contrato, E2E y performance tienen
directorios propios.

## Ejecución por categoría

```bash
make test-unit
make test-integration
make test-contract
make test-architecture
make test-e2e
make test-performance
```

`make test` ejecuta todo, pero deja la prueba de performance y la instalación
del wheel en modo opt-in. Cada categoría termina con un resumen uniforme de
ejecutadas, exitosas, fallidas, omitidas y duración. La salida auxiliar de los
componentes queda capturada para que un resultado exitoso no se vuelva ruidoso.

Los contract tests reales se omiten con un motivo explícito cuando falta
Poppler, Tesseract u Ollama. La inferencia real de Ollama también exige
`PDFSUM_CONTRACT_OLLAMA_MODEL`. La instalación del wheel en un entorno limpio
se habilita con `PDFSUM_RUN_PACKAGING=1`.

## Cobertura

La configuración mide líneas y branches, sin imponer por ahora un mínimo
artificial:

```bash
coverage run --branch -m unittest discover tests -v
coverage report -m
```

También puede usarse `make coverage`. La medición del 30 de agosto de 2026 se
hizo con Python 3.11 y reconstruyó el baseline desde el commit `fbfe50d`.

| Medición | Tests | Exitosos | Fallidos/errores | Omitidos | Líneas | Branches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 171 | 169 | 2 | 0 | 89,9% | 76,4% |
| Suite fortalecida | 221 | 216 | 0 | 5 | 94,8% | 82,1% |

Los dos errores del baseline estaban en mocks incompletos de `nvidia-smi` en
`test_observability`; no eran fallos de comportamiento en producción. Los
cinco omitidos actuales son tres contratos opcionales de Ollama, la performance
separada y la instalación limpia del wheel.

Cobertura actual de los adapters críticos:

| Módulo | Líneas |
| --- | ---: |
| `batch_runner.py` | 100,0% |
| `cloud_summarizer.py` | 100,0% |
| `job_store.py` | 100,0% |
| `ollama_summarizer.py` | 100,0% |
| `vlm_ocr.py` | 100,0% |
| `pdf_batch.py` | 98,3% |
| `summarizer_factory.py` | 96,8% |
| `ocr_transcriber.py` | 95,8% |

Los módulos con menos de 90% de líneas siguen siendo `config.py` (68,8%),
`api_server.py` (83,3%), `consolidation.py` (84,4%), `doctor.py` (89,2%) y
`observability.py` (aproximadamente 90,0%). Son los próximos candidatos para
casos de error y branches, no para assertions sin valor funcional.

## Mutation testing

La primera corrida queda limitada a `segment.py`, `qa.py`, `ocr_routing.py`,
`pipeline.py` y `adapters/pdf_batch.py`:

```bash
uv sync --group mutation
make mutation
python -m mutmut results
```

Resultado inicial: 1.170 mutantes generados, 752 muertos y 418 sobrevivientes,
sin timeout ni mutantes sospechosos. El score diagnóstico fue 64,3%. No hay
threshold obligatorio; los sobrevivientes de `pipeline`, `segment` y `qa`
deben orientar pruebas semánticas futuras.

## Alcance de las fixtures E2E

Las fixtures se generan en memoria para evitar binarios grandes en Git. El
corpus incluye PDF nativo, escaneado, multicolumna, tabla, gráfico, OCR malo,
multilingüe, largo simulado, casi vacío y corrompido. El flujo usa Poppler,
Tesseract, segmentación, pipeline, QA y reportes reales; solamente el LLM/VLM
no determinístico se sustituye por adapters determinísticos.
