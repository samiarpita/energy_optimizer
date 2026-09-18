# Multi-Stage Production Dockerfile for GridWise Energy Optimizer
# Stage 1: Build & Dependency Installation
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    coinor-cbc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Minimal Runtime Container
FROM python:3.11-slim AS runner

WORKDIR /app

# Install CBC solver runtime for PuLP optimization
RUN apt-get update && apt-get install -y --no-install-recommends \
    coinor-cbc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local

# Ensure local user bin is on PATH
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8000
ENV HOST=0.0.0.0

# Copy application source code
COPY app/ ./app/
COPY README.md .

# Expose HTTP port
EXPOSE 8000

# Start Uvicorn ASGI Server with dynamic $PORT support (Railway / Render compatible)
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
