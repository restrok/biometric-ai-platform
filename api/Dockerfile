# --- Build Stage ---
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

# Set the working directory
WORKDIR /app

# Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies directly into a virtual environment
# --frozen ensures we use the exact lockfile
# --no-dev skips development tools (like pytest, ruff, mypy)
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the application
COPY . .

# Final project sync to install the local package into the virtual environment
RUN uv sync --frozen --no-dev

# --- Runtime Stage ---
# Use a clean, slim Python image for the final artifact to minimize size and attack surface
FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files to disk and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy the pre-built virtual environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy the application code
COPY . .

# Ensure the PATH includes the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Create a directory for Garmin tokens to facilitate volume mounting
# This ensures the application has write permissions if running as a non-root user in the future
RUN mkdir -p /root/.garminconnect

# Expose FastAPI port
EXPOSE 8000

# Start the API
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
