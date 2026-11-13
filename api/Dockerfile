# --- Build Stage ---
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

WORKDIR /app

# Install git as it is required to download git-based dependencies (e.g., garmin-training-toolkit-sdk)
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1

# Copy dependency files first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies into virtual environment
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY . .

# Final project sync
RUN uv sync --frozen --no-dev

# --- Runtime Stage ---
FROM python:3.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Create a non-root system user and group for container security
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -d /home/appuser -s /bin/bash appuser

# Copy application code and virtual environment
COPY --chown=appuser:appgroup . .
COPY --chown=appuser:appgroup templates /app/templates
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv

# Ensure PATH includes the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Create directory for Garmin tokens and ensure write permissions for non-root user
RUN mkdir -p /home/appuser/.garminconnect /root/.garminconnect && \
    chown -R appuser:appgroup /home/appuser /app

# Expose FastAPI port
EXPOSE 8000

USER appuser

# Healthcheck to verify service availability
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')" || exit 1

# Start the API
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
