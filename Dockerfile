FROM python:3.11-slim

WORKDIR /app

COPY worker_requirements.txt .

RUN pip install --no-cache-dir -r worker_requirements.txt

COPY pdfsum_worker.py .

ENTRYPOINT ["python", "/app/pdfsum_worker.py"]
