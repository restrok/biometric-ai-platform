# Use a single stage to reduce disk I/O on Raspberry Pi
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Set the working directory
WORKDIR /app

# Enable bytecode compilation and optimization
ENV UV_COMPILE_BYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy dependency files first
COPY pyproject.toml uv.lock ./

# Install dependencies directly into the system/environment
# --frozen ensures we use the exact lockfile
# --no-dev skips development tools
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the application
COPY . .

# Final project sync
RUN uv sync --frozen --no-dev

# Create a directory for Garmin tokens
RUN mkdir -p /root/.garminconnect

# Expose FastAPI port
EXPOSE 8000

# Start the API using 'uv run' which is faster and manages the path automatically
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
