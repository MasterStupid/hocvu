# Multi-stage production image: builds the React Voice Assistant UI and serves it from FastAPI.
FROM node:22-slim AS frontend

RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json tsconfig.json .npmrc ./
COPY artifacts/hocvu/package.json ./artifacts/hocvu/
COPY scripts/package.json ./scripts/
RUN pnpm install --frozen-lockfile

COPY artifacts/hocvu ./artifacts/hocvu
RUN pnpm --filter @workspace/hocvu exec vite build --config vite.config.ts

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HV_SEMANTIC=0 \
    HV_BROWSER_AUTH=1 \
    HV_DATA_DIR=/var/data \
    HV_UI_DIR=/app/dist/public

WORKDIR /app

# Tesseract provides Vietnamese OCR for uploaded scans and image-only PDFs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.production.txt ./requirements.production.txt
RUN pip install --no-cache-dir -r requirements.production.txt

COPY artifacts/hocvu/app ./
COPY --from=frontend /workspace/artifacts/hocvu/dist/public ./dist/public
RUN mkdir -p /var/data

EXPOSE 10000

CMD ["sh", "-c", "python manage.py serve --host 0.0.0.0 --port ${PORT:-10000}"]
