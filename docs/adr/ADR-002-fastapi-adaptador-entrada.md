# ADR-002 — FastAPI como adaptador de entrada para el modo servicio (FASE20)

## Estado

Propuesto (2026-09-02) → Aprobado por PO (2026-09-03)

## Contexto

`pdfsum serve` (http.server) expone solo lectura sobre un lote ya generado.
El objetivo de FASE20 es operar como **servicio**: subir PDFs y producir
resúmenes con QA de forma asíncrona (API encola, worker procesa), manteniendo
hexagonal + DDD (dominio no depende de frameworks).

Requisitos del adaptador de entrada:
- Upload multipart robusto
- Límites de tamaño (413)
- Autenticación Bearer obligatoria
- OpenAPI/contratos claros para la célula BIREME
- Manejo correcto de errores y tipos

## Decisión

Usar **FastAPI** (y `uvicorn`) como **dependencia opcional** vía extra
`pdfsum[service]`.

- El core sigue stdlib-first (solo Pillow como dependencia base).
- El modo servicio (`pdfsum api`) falla con un mensaje claro si el extra no
  está instalado.
- El dominio no importa `fastapi`/`uvicorn`; solo el adaptador en
  `src/pdfsum/adapters/api_service.py`.

## Alternativas consideradas

1. **http.server (stdlib)**
   - Pros: cero dependencias.
   - Contras: upload multipart y límites fiables requieren mucha lógica ad-hoc;
     sin OpenAPI; más superficie de bug de seguridad.

2. **Flask**
   - Pros: simple.
   - Contras: menos tipado, sin OpenAPI por defecto; se acaba añadiendo
     tooling adicional.

3. **Starlette puro**
   - Pros: ligero.
   - Contras: FastAPI añade OpenAPI y ergonomía con el mismo runtime.

## Consecuencias

- Se añade un extra opcional `service` (FastAPI/uvicorn/python-multipart/httpx).
- CI instala esas dependencias (en dev group) para correr tests del servicio.
- La operación productiva sigue el patrón: reverse proxy (TLS) → API → worker.
