# syntax=docker/dockerfile:1.6
# ===== MULTI-STAGE BUILD FOR PYDANTIC-LLM-MIXIN =====
# Example deployment container for Railway/production use

FROM python:3.11-slim AS base

SHELL ["/bin/bash", "-euxo", "pipefail", "-c"]

# Prevent debconf warnings in Docker
ENV DEBIAN_FRONTEND=noninteractive

# Build arguments for environment variables (Railway passes these)
ARG GROQ_API_KEY
ARG PORT=8080

# Install system dependencies (minimal base for cache sharing)
RUN apt-get update && apt-get install -y \
    curl ca-certificates gnupg wget git \
    build-essential pkg-config python3-dev \
    libffi-dev libssl-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install uv
RUN python -m pip install --upgrade pip && pip install uv

# Create appuser
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

ENV PATH="/home/appuser/.local/bin:$PATH"

# ===== Stage 2: Python dependencies =====
FROM base AS python-deps

SHELL ["/bin/bash", "-euxo", "pipefail", "-c"]

USER appuser
WORKDIR /app

# Copy dependency files and source code
COPY --chown=appuser:appuser pyproject.toml README.md ./
COPY --chown=appuser:appuser src/ ./src/

# Create virtual environment
RUN uv venv

# Install package and dependencies using UV (including railway extras for FastAPI/uvicorn)
RUN uv pip install -e ".[railway]"

# ===== Stage 3: Application code =====
FROM python-deps AS production

# Switch back to root temporarily to set permissions
USER root

# Set environment for uv virtual environment
ENV PATH="/home/appuser/.local/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"
ENV PATH="/app/.venv/bin:$PATH"

# Copy all Python source code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser examples/ ./examples/

# Fix all permissions at build time
RUN chown -R appuser:appuser /app && \
    chmod -R 755 /app

# Set environment variables
ENV PYTHONPATH=/app
ENV ENVIRONMENT=production
ENV LOG_LEVEL=INFO

# Pass build args as runtime environment variables
ARG GROQ_API_KEY
ARG PORT=8080
ENV GROQ_API_KEY=${GROQ_API_KEY}
ENV PORT=${PORT}

# Railway sets PORT at runtime, EXPOSE for documentation
EXPOSE ${PORT}

# Switch to non-root user for execution
USER appuser

# Run the FastAPI server with hot reload
WORKDIR /app
CMD ["sh", "-c", "uv run uvicorn examples.railway_deployment:app --host 0.0.0.0 --port ${PORT} --reload"]
