FROM python:3.11-slim AS base
WORKDIR /app

# build-essential is required to compile C extensions used by some NLP
# packages (e.g. sentencepiece, tokenizers) at install time
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
RUN pip install uv --no-cache-dir

# Install shared local package first
COPY sse_common/ /sse_common/
RUN uv pip install --system --no-cache /sse_common

# Copy dependency spec first so this layer is cached unless pyproject.toml changes
COPY processor/pyproject.toml .
COPY processor/src/ src/
RUN uv pip install --system --no-cache -e "."

# HuggingFace model cache (mounted as a named volume in docker-compose so
# FinBERT weights (~1.4 GB) survive container restarts without re-downloading)
ENV HF_HOME=/app/.cache/huggingface
RUN mkdir -p /app/.cache/huggingface

# Non-root user (TASK-OPS03): dedicated low-privilege user, no interactive shell
# docker-compose sets memory limit: 2G (hard) / 1500M (reservation) — TASK-OPS32
RUN useradd -m -u 1001 -s /sbin/nologin processor \
    && chown -R processor:processor /app
USER processor

CMD ["python", "-m", "processor.main"]
