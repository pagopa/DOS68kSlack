# ---- Build stage ----
    FROM python:3.12-slim AS builder

    WORKDIR /app
    
    COPY requirements.txt .
    RUN pip install --no-cache-dir --upgrade pip \
        && pip install --no-cache-dir -r requirements.txt
    
    # ---- Final stage ----
    FROM python:3.12-slim
    
    # Non root user per sicurezza
    RUN groupadd -r appuser && useradd -r -g appuser appuser
    
    WORKDIR /app
    
    COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
    COPY --from=builder /usr/local/bin /usr/local/bin
    COPY src/ ./src/
    
    USER appuser
    
    EXPOSE 8000
    
    # Uvicorn come ASGI server; workers scalabili tramite env var
    CMD ["uvicorn", "src.app:app", \
         "--host", "0.0.0.0", \
         "--port", "8000", \
         "--workers", "2", \
         "--log-level", "info", \
         "--access-log"]