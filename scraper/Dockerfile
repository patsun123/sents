FROM python:3.11-slim AS base
WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv --no-cache-dir

# Install shared local package first
COPY sse_common/ /sse_common/
RUN uv pip install --system --no-cache /sse_common

# Copy dependency spec first so this layer is cached unless pyproject.toml changes
COPY scraper/pyproject.toml .
COPY scraper/src/ src/
RUN uv pip install --system --no-cache -e "."

# Non-root user (TASK-OPS03): dedicated low-privilege user, no interactive shell
RUN useradd -m -u 1001 -s /sbin/nologin scraper \
    && chown -R scraper:scraper /app
USER scraper

CMD ["python", "-m", "scraper.main"]
