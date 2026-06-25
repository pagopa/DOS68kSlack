"""
DOS68K Slack Bot - Entry point.

Exposes a FastAPI endpoint compatible with ECS/Lambda.
Handles Slack events with the ACK + background task pattern:
  1. Verifies the Slack signature and responds 200 OK immediately
  2. Processes the event in background (avoids Slack retries after 3s)
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
    logger.info("DOS68K Slack Bot started")
    yield
    logger.info("DOS68K Slack Bot stopped")


app = FastAPI(
    title="DOS68K Slack Bot",
    version="1.0.0",
    lifespan=lifespan,
)

slack_handler = SlackHandler()


@app.get("/health")
async def health():
    """Health check – not logged if LOG_HEALTH_CHECKS=false."""
    return {"status": "ok"}


@app.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    """
    Receives all events from the Slack Events API.

    ACK + background pattern:
    - Verifies signature and handles challenge synchronously
    - For all other events responds 200 OK immediately
      and processes the query in background, avoiding Slack retries
      that trigger after 3 seconds without a response.
    """
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    headers = dict(request.headers)

    # Signature verification and challenge handling: must be synchronous
    ack, status_code = await slack_handler.ack(headers, body_str)
    if ack is not None:
        return Response(content=ack, status_code=status_code, media_type="application/json")

    # Immediate ACK to Slack — processing happens in background
    background_tasks.add_task(slack_handler.process, headers, body_str)
    return Response(content='{"ok": true}', status_code=200, media_type="application/json")
