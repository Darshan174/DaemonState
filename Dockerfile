# ── Stage 1: Build the React frontend ────────────────────────────────────────
FROM node:24-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci --prefer-offline

COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python runtime (backend + serves built frontend) ─────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install the packaged application and immutable migration resources together.
# The migration gate and API/worker schema probes both resolve alembic.ini from
# this runtime working directory.
COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY app ./app
RUN pip install --no-cache-dir .
RUN git --version \
    && python -c "from app.database import expected_schema_revisions; assert expected_schema_revisions()"

# Copy built frontend from stage 1
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Run the normal image as an unprivileged identity. The hardened production
# entrypoint may start as root solely to read file-backed secrets, then drops
# irreversibly to this same UID/GID before importing application code.
RUN groupadd --gid 10001 daemonstate \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin daemonstate \
    && mkdir -p /data \
    && chown -R 10001:10001 /app /data
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

USER 10001:10001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
