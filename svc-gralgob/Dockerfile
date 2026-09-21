# =============================================================================
# svc-gralgob — Multi-stage Dockerfile (Fase 0: sync)
# =============================================================================

FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir .

FROM python:3.12-slim AS runtime

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Sin credenciales en la imagen; ADC se resuelve vía la identidad de runtime de Cloud Run
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
