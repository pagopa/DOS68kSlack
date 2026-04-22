"""
DOS68K Slack Bot - Entry point.

Espone un endpoint FastAPI compatibile con ECS/Lambda.
Gestisce gli eventi Slack e li instrada al chatbot DOS68K.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

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
async def slack_events(request: Request):
    """Riceve tutti gli eventi dalla Slack Events API."""
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    headers = dict(request.headers)

    response_body, status_code = await slack_handler.handle(headers, body_str)
    return Response(
        content=response_body,
        status_code=status_code,
        media_type="application/json",
    )