FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-por \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app

# Para el modo servicio (FASE20), la imagen incluye el extra opcional.
RUN pip install --no-cache-dir '.[service]'

CMD ["pdfsum", "--help"]
