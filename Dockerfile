FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app
COPY frontend ./frontend
RUN corepack enable \
    && pnpm --dir frontend install --frozen-lockfile \
    && pnpm --dir frontend build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY scripts/serve.py ./scripts/serve.py
COPY --from=frontend-build /app/backend/static ./backend/static

EXPOSE 7860
CMD ["python", "scripts/serve.py", "--host", "0.0.0.0", "--port", "7860", "--runtime", "/data/index"]
