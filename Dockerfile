# Stage 1: build the static frontend
FROM node:20-slim AS frontend
WORKDIR /build
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python app, serving the API and the frontend on one port
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 UV_NO_CACHE=1
RUN pip install --no-cache-dir uv==0.13.7 \
    && useradd --create-home finally \
    && mkdir -p /app/db /app/backend \
    && chown finally:finally /app/db

WORKDIR /app/backend

# Dependencies first, so code changes don't reinstall them
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-install-project
COPY backend/app ./app
RUN uv sync --frozen --no-editable
COPY --from=frontend /build/out ./static

USER finally
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["/app/backend/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]

# Exec form, so the server receives SIGTERM from docker stop
CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
