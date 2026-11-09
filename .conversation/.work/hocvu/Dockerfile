# A small production image for Render (or any Docker-compatible host).
# Python 3.12 has broad wheel support for the PDF/OCR dependencies.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HV_SEMANTIC=0 \
    HV_DATA_DIR=/var/data

WORKDIR /app

# Tesseract provides Vietnamese OCR for uploaded scans and image-only PDFs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.production.txt ./requirements.production.txt
RUN pip install --no-cache-dir -r requirements.production.txt

COPY . .
RUN mkdir -p /var/data

EXPOSE 10000

CMD ["sh", "-c", "python manage.py serve --host 0.0.0.0 --port ${PORT:-10000}"]
