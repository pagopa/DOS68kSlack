"""
Main Slack event orchestrator.

Flow for each received message:
  1. ack()     → verifies signature + handles challenge, responds within 3s
  2. process() → background processing (creates session, sends query, responds)

Deduplication:
  Slack may resend the same event if no response is received within 3s.
  Processed event_ids are kept in memory (with 5-minute TTL)
  to ignore duplicates.

Active session management:
  The slack_user_id → active session_id mapping is kept in an in-memory
  dictionary (_active_sessions). Does not persist across container restarts.
"""

import asyncio
import json
import logging
import time
from typing import Tuple

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

from src.config import settings
from src.slack_verifier import verify_slack_request, SlackVerificationError
from src.chatbot_client import DOS68KClient, ChatbotAPIError, SessionNotFoundError

logger = logging.getLogger(__name__)

# In-memory mapping: slack_user_id → active session_id
_active_sessions: dict[str, str] = {}

# Cache of processed event_ids: event_id → timestamp
# Prevents double-processing of Slack retries
_processed_events: dict[str, float] = {}
_EVENT_TTL = 300  # 5 minutes


HELP_TEXT = """*DOS68K Slack Bot* – Available commands:
• `new` – Creates a new session and sets it as active
• `list` – Lists existing sessions with their IDs
• `resume <id>` – Resumes a previous session
• `help` – Shows this message

Any other text is sent as a question to the chatbot on the active session.
If there is no active session, one is created automatically.
"""


def _is_duplicate(event_id: str) -> bool:
    """Returns True if the event has already been processed."""
    now = time.time()
    # Clean up expired entries
    expired = [k for k, v in _processed_events.items() if now - v > _EVENT_TTL]
    for k in expired:
        del _processed_events[k]

    if event_id in _processed_events:
        logger.info(f"Duplicate event ignored: {event_id}")
        return True

    _processed_events[event_id] = now
    return False


class SlackHandler:
    def __init__(self):
        self._slack = AsyncWebClient(token=settings.slack_bot_token)
        self._chatbot = DOS68KClient()

    async def ack(self, headers: dict, body_str: str) -> Tuple[str | None, int]:
        """
        Verifies the signature and handles cases requiring a synchronous response.
        Returns (response_body, status_code) if a direct response is needed,
        or (None, 200) if the event should be processed in background.
        """
        try:
            verify_slack_request(headers, body_str)
        except SlackVerificationError as e:
            logger.warning(f"Signature verification failed: {e}")
            return json.dumps({"error": "Forbidden"}), 403

        body = json.loads(body_str)

        # URL verification challenge (initial Slack App setup) — synchronous response required
        if body.get("type") == "url_verification":
            logger.info("Slack URL verification challenge received")
            return json.dumps({"challenge": body["challenge"]}), 200

        return None, 200

    async def process(self, headers: dict, body_str: str) -> None:
        """
        Asynchronous event processing (executed in background).
        Handles deduplication and routes to the correct method.
        """
        body = json.loads(body_str)
        event_id = body.get("event_id", "")

        # Deduplication: ignore Slack retries
        if event_id and _is_duplicate(event_id):
            return

        event = body.get("event", {})
        event_type = event.get("type", "")

        if event_type == "message":
            # Respond only to direct messages (DM), not to channel messages.
            # In channels, respond exclusively via app_mention (@Discovery68k).
            # channel_type="im" = DM, "group" = private channel, "channel" = public.
            channel_type = event.get("channel_type", "")
            if channel_type == "im":
                await self._handle_message(event)
            else:
                logger.debug("Channel message ignored (use @Discovery68k to interact)")
        elif event_type == "app_mention":
            await self._handle_message(event, strip_mention=True)
        else:
            logger.debug(f"Event ignored: {event_type}")

    async def _handle_message(self, event: dict, strip_mention: bool = False) -> None:
        if event.get("bot_id") or event.get("subtype"):
            return

        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = (event.get("text") or "").strip()

        if not user_id or not text:
            return

        if strip_mention:
            parts = text.split(maxsplit=1)
            text = parts[1].strip() if len(parts) > 1 else ""
            if not text:
                return

        cmd = text.lower().strip()
        parts = text.split(maxsplit=1)

        if cmd == "help":
            await self._post(channel_id, HELP_TEXT)
        elif cmd == "new":
            await self._cmd_new(user_id, channel_id)
        elif cmd == "list":
            await self._cmd_list(user_id, channel_id)
        elif cmd.startswith("resume "):
            session_id = parts[1].strip() if len(parts) > 1 else ""
            await self._cmd_resume(user_id, channel_id, session_id)
        else:
            await self._cmd_query(user_id, channel_id, text)

    async def _cmd_new(self, user_id: str, channel_id: str) -> None:
        try:
            session_id = await self._chatbot.create_session(
                slack_user_id=user_id,
                title=f"Slack – {user_id}",
            )
            _active_sessions[user_id] = session_id
            await self._post(
                channel_id,
                f"✅ New session created and set as active.\nID: `{session_id}`",
            )
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Error creating session (HTTP {e.status_code}).")

    async def _cmd_list(self, user_id: str, channel_id: str) -> None:
        try:
            sessions = await self._chatbot.list_sessions(user_id)
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Error retrieving sessions (HTTP {e.status_code}).")
            return

        if not sessions:
            await self._post(channel_id, "You have no previous sessions. Use `new` to start one.")
            return

        active_id = _active_sessions.get(user_id)
        lines = ["*Your sessions:*"]
        for s in sessions:
            sid = s.get("id", "?")
            title = s.get("title", "—")
            created = s.get("createdAt", "")[:10]
            marker = " ◀ *active*" if sid == active_id else ""
            lines.append(f"• `{sid}` – _{title}_ ({created}){marker}")
        lines.append("\nUse `resume <id>` to resume a session.")
        await self._post(channel_id, "\n".join(lines))

    async def _cmd_resume(self, user_id: str, channel_id: str, session_id: str) -> None:
        if not session_id:
            await self._post(channel_id, "Correct usage: `resume <id>`")
            return
        try:
            await self._chatbot.get_session(user_id, session_id)
            _active_sessions[user_id] = session_id
            await self._post(channel_id, f"✅ Session `{session_id}` resumed. You can continue writing.")
        except SessionNotFoundError:
            await self._post(channel_id, f"⚠️ Session `{session_id}` not found. Use `list` to see available sessions.")
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Error verifying session (HTTP {e.status_code}).")

    async def _cmd_query(self, user_id: str, channel_id: str, text: str) -> None:
        session_id = _active_sessions.get(user_id)

        if not session_id:
            try:
                session_id = await self._chatbot.create_session(
                    slack_user_id=user_id,
                    title=f"Slack – {user_id}",
                )
                _active_sessions[user_id] = session_id
                logger.info(f"Session auto-created: {session_id} for user {user_id}")
            except ChatbotAPIError as e:
                await self._post(channel_id, f"⚠️ Error creating session (HTTP {e.status_code}).")
                return

        # Show the "typing" placeholder immediately
        placeholder_ts = await self._post_thinking(channel_id)

        try:
            answer = await self._chatbot.send_query(user_id, session_id, text)
            await self._update_or_post(channel_id, placeholder_ts, answer)

        except SessionNotFoundError:
            logger.warning(f"Session {session_id} expired, auto-recreating...")
            _active_sessions.pop(user_id, None)
            try:
                session_id = await self._chatbot.create_session(
                    slack_user_id=user_id,
                    title=f"Slack – {user_id}",
                )
                _active_sessions[user_id] = session_id
                answer = await self._chatbot.send_query(user_id, session_id, text)
                await self._update_or_post(channel_id, placeholder_ts, answer)
            except ChatbotAPIError as e:
                await self._update_or_post(channel_id, placeholder_ts, f"⚠️ Error (HTTP {e.status_code}). Please try again.")

        except ChatbotAPIError as e:
            logger.error(f"DOS68K API error: {e}")
            await self._update_or_post(
                channel_id, placeholder_ts,
                f"⚠️ Error contacting the chatbot (HTTP {e.status_code}). Please try again.",
            )
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            await self._update_or_post(channel_id, placeholder_ts, "⚠️ An unexpected error occurred. Please try again.")

    async def _post_thinking(self, channel: str) -> str | None:
        """
        Posts a visible placeholder message while the chatbot processes.
        Returns the message timestamp (used to update it afterwards).
        """
        try:
            resp = await self._slack.chat_postMessage(
                channel=channel,
                text="_⏳ Processing your request..._",
            )
            return resp.get("ts")
        except SlackApiError as e:
            logger.error(f"Error sending placeholder: {e}")
            return None

    async def _update_or_post(self, channel: str, ts: str | None, text: str) -> None:
        """
        Updates the placeholder message with the final response.
        If for any reason the timestamp is not available, sends a new message.
        """
        if ts:
            try:
                await self._slack.chat_update(channel=channel, ts=ts, text=text)
                return
            except SlackApiError as e:
                logger.warning(f"Unable to update message ({e}), sending new message")
        # Fallback: new message
        await self._post(channel, text)

    async def _post(self, channel: str, text: str) -> None:
        try:
            await self._slack.chat_postMessage(channel=channel, text=text)
        except SlackApiError as e:
            logger.error(f"Error sending Slack message: {e}")
