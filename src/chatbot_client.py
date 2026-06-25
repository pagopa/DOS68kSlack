"""
HTTP client for the DOS68K APIs (PagoPA chatbot).

This module is the ONLY interface towards the DOS68K backend.

Endpoints used:
  POST /sessions                → creates a new session
  POST /queries/{session_id}    → sends a question, receives answer
  DELETE /sessions/{session_id} → deletes the session (reset command)
  POST /sessions/{session_id}/clear → resets the session history

Authentication:
  x-api-key    → CHATBOT_API_KEY  (all requests)
  x-user-id    → UUID derived from slack_user_id (all requests)
  X-User-Role  → same UUID as x-user-id (all requests)
"""

import logging
import uuid

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60.0


class ChatbotAPIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"ChatbotAPI {status_code}: {detail}")


class SessionNotFoundError(ChatbotAPIError):
    """Session not found or expired on the DOS68K side."""
    pass


class DOS68KClient:
    """Async client for the DOS68K APIs."""

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.chatbot_base_url,
            timeout=_DEFAULT_TIMEOUT,
            headers={
                "Content-Type": "application/json",
                "x-api-key": settings.chatbot_api_key,
            },
        )

    def _user_headers(self, slack_user_id: str) -> dict:
        """
        Derives a stable UUID from the Slack ID for the x-user-id header.
        uuid5 is deterministic: same slack_user_id → same UUID always.
        """
        user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"slack:{slack_user_id}"))
        return {"x-user-id": user_uuid, "X-User-Role": user_uuid}

    async def create_session(self, slack_user_id: str, title: str = "Slack Chat") -> str:
        """Creates a new session on DOS68K and returns the session_id."""
        logger.info(f"Creating DOS68K session for user={self._user_headers(slack_user_id)} title={title}")
        resp = await self._client.post(
            "/sessions",
            json={"title": title, "isTemporary": False},
            headers=self._user_headers(slack_user_id),
        )
        self._raise_for_status(resp)
        session_id = resp.json()["id"]
        logger.info(f"DOS68K session created: session_id={session_id} user={slack_user_id}")
        return session_id


    async def get_session(self, slack_user_id: str, session_id: str) -> dict:
        """
        Verifies that the session exists on DOS68K.
        Used by `resume` to validate the ID provided by the user.
        Raises SessionNotFoundError if the session does not exist or has expired.
        """
        resp = await self._client.get(
            f"/sessions/{session_id}",
            headers=self._user_headers(slack_user_id),
        )
        if resp.status_code == 404:
            raise SessionNotFoundError(404, f"Session {session_id} not found")
        self._raise_for_status(resp)
        return resp.json()

    async def list_sessions(self, slack_user_id: str) -> list[dict]:
        """
        Retrieves all user sessions from DOS68K.
        Used by the `list` command.
        """
        resp = await self._client.get(
            "/sessions/all",
            headers=self._user_headers(slack_user_id),
        )
        self._raise_for_status(resp)
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("sessions", [])

    async def send_query(self, slack_user_id: str, session_id: str, question: str) -> str:
        """Sends a question to the chatbot and returns the text answer."""
        logger.info(f"Query → session={session_id} question={question[:80]}...")
        resp = await self._client.post(
            f"/queries/{session_id}",
            json={"question": question},
            headers=self._user_headers(slack_user_id),
        )
        self._raise_for_status(resp)
        data = resp.json()
        return (
            data.get("answer")
            or data.get("response")
            or data.get("content")
            or data.get("text")
            or str(data)
        )

    async def delete_session(self, slack_user_id: str, session_id: str) -> None:
        """Permanently deletes the session on DOS68K."""
        resp = await self._client.delete(
            f"/sessions/{session_id}",
            headers=self._user_headers(slack_user_id),
        )
        if resp.status_code == 404:
            logger.warning(f"Session {session_id} already absent on DOS68K, ignoring")
            return
        self._raise_for_status(resp)
        logger.info(f"Session {session_id} deleted on DOS68K")

    async def clear_session(self, slack_user_id: str, session_id: str) -> None:
        """Resets the session history (keeps the session open)."""
        resp = await self._client.post(
            f"/sessions/{session_id}/clear",
            headers=self._user_headers(slack_user_id),
        )
        self._raise_for_status(resp)
        logger.info(f"Session {session_id} cleared")

    async def close(self):
        await self._client.aclose()

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise ChatbotAPIError(resp.status_code, resp.text[:500])
