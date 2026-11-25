# ---- Build stage ----
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b AS builder

COPY --from=ghcr.io/astral-sh/uv:0.4.30@sha256:341e448d2ca38f11d8e2768db5464b4c95a4d87f539b8cb7511db86b02fef97e /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/

# ---- Final stage ----
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

# Non root user per sicurezza
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

# Uvicorn come ASGI server; workers scalabili tramite env var
CMD ["uvicorn", "src.app:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info", \
     "--access-log"]