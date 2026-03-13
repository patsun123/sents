FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY src/ src/

# Health check: verify the .health file exists and was written within the last
# 1200 seconds (20 minutes = one cycle interval + 5 minutes grace).
# The worker writes .health after each successful or partial cycle.
HEALTHCHECK --interval=20m --timeout=10s --retries=3 --start-period=60s \
  CMD python -c "import os, time; f='.health'; \
    assert os.path.exists(f) and time.time()-os.path.getmtime(f) < 1200, \
    'No successful cycle in last 20 minutes'"

CMD ["python", "-m", "worker"]
