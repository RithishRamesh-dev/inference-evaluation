# ── Stage 1: build frontend ───────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
ARG VITE_API_KEY=change-me-in-prod
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build


# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./backend/static

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
