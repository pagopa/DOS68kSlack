"""
DOS68K Slack Bot - Entry point.

Espone un endpoint FastAPI compatibile con ECS/Lambda.
Gestisce gli eventi Slack con il pattern ACK + background task:
  1. Verifica la firma Slack e risponde 200 OK immediatamente
  2. Processa l'evento in background (evita i retry di Slack dopo 3s)
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request, Response

from src.config import settings
from src.slack_handler import SlackHandler
from src.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("DOS68K Slack Bot avviato")
    yield
    logger.info("DOS68K Slack Bot spento")


app = FastAPI(
    title="DOS68K Slack Bot",
    version="1.0.0",
    lifespan=lifespan,
)

slack_handler = SlackHandler()


@app.get("/health")
async def health():
    """Health check – non loggato se LOG_HEALTH_CHECKS=false."""
    return {"status": "ok"}


@app.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    """
    Riceve tutti gli eventi dalla Slack Events API.

    Pattern ACK + background:
    - Verifica la firma e gestisce il challenge in modo sincrono
    - Per tutti gli altri eventi risponde 200 OK immediatamente
      e processa la query in background, evitando i retry di Slack
      che scattano dopo 3 secondi senza risposta.
    """
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    headers = dict(request.headers)

    # Verifica firma e gestione challenge: devono essere sincroni
    ack, status_code = await slack_handler.ack(headers, body_str)
    if ack is not None:
        return Response(content=ack, status_code=status_code, media_type="application/json")

    # ACK immediato a Slack — il processing avviene in background
    background_tasks.add_task(slack_handler.process, headers, body_str)
    return Response(content='{"ok": true}', status_code=200, media_type="application/json")