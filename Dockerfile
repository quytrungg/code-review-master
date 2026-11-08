# syntax=docker/dockerfile:1

# --- Frontend: compile the SPA -------------------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


# --- Runtime: FastAPI + Alembic + built SPA ------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SKILLS_DIR=/data/code-review \
    SKILLS_SEED_DIR=/opt/code-review \
    FOUNDATIONS_DIR=/data/foundations \
    FRONTEND_DIR=/app/frontend/dist \
    DATABASE_URL=sqlite:////data/app.db

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# The bundled library stays pristine in the image; the entrypoint seeds the volume from it.
COPY code-review/ /opt/code-review/
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && useradd --create-home --uid 10001 app \
 && mkdir -p /data/foundations \
 && chown -R app:app /data

USER app

# SQLite database, the seeded default skill library and uploaded foundations survive a restart.
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

ENTRYPOINT ["docker-entrypoint.sh"]

# One worker by default: SQLite is the default database, and the container mode keeps ingest on
# the request loop (`asyncio.create_task`). Progress events are database rows, so extra workers no
# longer split the SSE stream; scale them only with PostgreSQL.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
