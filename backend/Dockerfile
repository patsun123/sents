FROM python:3.11-slim AS base
WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv --no-cache-dir

# Install shared local package first
COPY sse_common/ /sse_common/
RUN uv pip install --system --no-cache /sse_common

# Copy dependency spec first so this layer is cached unless pyproject.toml changes
COPY backend/pyproject.toml .
COPY backend/app/ app/
RUN uv pip install --system --no-cache -e "."

# Non-root user (TASK-OPS03): dedicated low-privilege user, no interactive shell
RUN useradd -m -u 1001 -s /sbin/nologin api \
    && chown -R api:api /app
USER api

EXPOSE 8000

# Worker count defaults to 2; override via UVICORN_WORKERS env var in docker-compose
# (e.g. UVICORN_WORKERS=4 for a larger droplet)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
