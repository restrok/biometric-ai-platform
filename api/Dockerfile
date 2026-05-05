# Use the official uv image for a fast and reliable build
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

# Set the working directory
WORKDIR /app

# Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies (excluding dev dependencies)
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the application
COPY . .

# Install the project itself
RUN uv sync --frozen --no-dev

# --- Final Runtime Image ---
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install runtime dependencies (e.g., for playwright if needed in the future, 
# but keeping it slim for now as the current refresh logic is requests-based)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     libglib2.0-0 \
#     ... && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Copy the application code
COPY . .

# Ensure the PATH includes the virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Create a directory for Garmin tokens to facilitate volume mounting
RUN mkdir -p /root/.garminconnect

# Expose FastAPI port
EXPOSE 8000

# Start the API
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
