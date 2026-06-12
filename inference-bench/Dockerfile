FROM python:3.11-slim AS builder

# ── Stage 1: build frontend ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./frontend/
RUN cd frontend && npm ci

COPY frontend/ ./frontend/
# VITE_API_KEY is baked at build time; override via build arg if needed
ARG VITE_API_KEY=change-me-in-prod
ENV VITE_API_KEY=$VITE_API_KEY
RUN cd frontend && npm run build


# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY --from=builder /app/frontend/dist ./backend/static

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
