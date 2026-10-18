# ingest-api service image. Build context: repository root.
# Multi-stage: the builder compiles any sdist into wheels (s390x has few PyPI wheels,
# see docs/vm-check.md section 4); the runtime stage installs only the wheels.
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN apt-get update     && apt-get install -y --no-install-recommends build-essential pkg-config libssl-dev     && rm -rf /var/lib/apt/lists/*
COPY services/common/requirements.txt /requirements/common.txt
COPY services/ingest_api/requirements.txt /requirements/service.txt
RUN pip wheel --wheel-dir /wheels -r /requirements/common.txt -r /requirements/service.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --create-home --uid 10001 app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* && rm -rf /wheels
WORKDIR /app
COPY services/__init__.py services/__init__.py
COPY services/common services/common
COPY services/ingest_api services/ingest_api
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3     CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["uvicorn", "services.ingest_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
