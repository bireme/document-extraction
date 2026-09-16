# PDFSum Worker

Worker de orquestación para procesamiento remoto de documentos.

## Arquitectura

MongoDB → Worker → PDFSum Processing API
              ↓
           MongoDB

## Responsabilidades

- leer registros de `mis`;
- seleccionar la URL PDF;
- controlar `document_extraction_jobs`;
- llamar `POST /api/pdfsum`;
- persistir resultados.

El worker no procesa PDFs localmente.

## Variables de entorno

- `PDFSUM_MONGODB_URI`
- `PDFSUM_SERVER_URL`

## Ejecución

docker compose up -d --build
