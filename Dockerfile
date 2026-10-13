# syntax=docker/dockerfile:1.7
# Single-container build: the API also serves the React app (one service, one origin).
# Used for hosted deploys such as Render (see render.yaml and docs/deploy.md).
# docker-compose keeps using backend/ and frontend/ images separately.

# ---- 1. build the web app
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. build Python wheels
FROM python:3.12-slim AS wheels
WORKDIR /src
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

# ---- 3. runtime
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUPPORT_KB_DIR=/app/knowledge_base \
    SUPPORT_STATIC_DIR=/app/static
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY --chown=app backend/alembic.ini ./
COPY --chown=app backend/alembic ./alembic
COPY --chown=app backend/knowledge_base ./knowledge_base
COPY --chown=app --from=web /web/dist ./static
COPY --chown=app deploy/start.sh ./start.sh
USER app
EXPOSE 8000
CMD ["sh", "/app/start.sh"]
