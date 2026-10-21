# syntax=docker/dockerfile:1.7
# One image, one origin: FastAPI serves the API and the built React app, so the
# SameSite=Strict refresh cookie and the strict CSP work without CORS.

FROM node:24-alpine AS web
WORKDIR /web
COPY Frontend/package.json Frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Frontend/ ./
# Public values baked into the SPA bundle (the publishable key is designed to be public).
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY
RUN npm run build

FROM python:3.13-slim AS api
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY Backend/pyproject.toml Backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY Backend/app ./app

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 sap
WORKDIR /app
COPY --from=api /app /app
COPY --from=web /web/dist /app/static
ENV PATH="/app/.venv/bin:$PATH" \
    SAP_ENV=prod \
    SAP_STATIC_DIR=/app/static \
    SAP_DATA_DIR=/data \
    SAP_COOKIE_SECURE=true
RUN mkdir -p /data && chown sap:sap /data
USER sap
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
