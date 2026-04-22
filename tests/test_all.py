"""
Unit test per DOS68K Slack Bot.
Eseguiti da pytest prima di ogni build Docker (punto aperto #2).
"""

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_SIGNING_SECRET = "test_secret_abc123"
FAKE_BOT_TOKEN = "xoxb-fake-token"
FAKE_CHATBOT_API_KEY = "fake-api-key"
FAKE_CHATBOT_URL = "https://fake-chatbot.example.com"


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", FAKE_SIGNING_SECRET)
    monkeypatch.setenv("SLACK_BOT_TOKEN", FAKE_BOT_TOKEN)
    monkeypatch.setenv("CHATBOT_API_KEY", FAKE_CHATBOT_API_KEY)
    monkeypatch.setenv("CHATBOT_BASE_URL", FAKE_CHATBOT_URL)
    monkeypatch.setenv("LOG_HEALTH_CHECKS", "false")
    monkeypatch.setenv("LOG_LEVEL", "INFO")


def _make_slack_signature(body: str, secret: str = FAKE_SIGNING_SECRET) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    sig_basestring = f"v0:{timestamp}:{body}"
    signature = "v0=" + hmac.new(
        secret.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()
    return timestamp, signature


# ---------------------------------------------------------------------------
# Test: slack_verifier
# ---------------------------------------------------------------------------

class TestSlackVerifier:

    def test_valid_signature_passes(self):
        from src.slack_verifier import verify_slack_request
        body = '{"type": "url_verification"}'
        ts, sig = _make_slack_signature(body)
        headers = {"x-slack-request-timestamp": ts, "x-slack-signature": sig}
        verify_slack_request(headers, body)

    def test_invalid_signature_raises(self):
        from src.slack_verifier import verify_slack_request, SlackVerificationError
        body = '{"type": "message"}'
        ts, _ = _make_slack_signature(body)
        headers = {
            "x-slack-request-timestamp": ts,
            "x-slack-signature": "v0=invalidsignature",
        }
        with pytest.raises(SlackVerificationError, match="Firma Slack non valida"):
            verify_slack_request(headers, body)

    def test_old_timestamp_raises(self):
        from src.slack_verifier import verify_slack_request, SlackVerificationError
        body = '{"type": "message"}'
        old_ts = str(int(time.time()) - 400)
        sig_basestring = f"v0:{old_ts}:{body}"
        sig = "v0=" + hmac.new(
            FAKE_SIGNING_SECRET.encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()
        headers = {"x-slack-request-timestamp": old_ts, "x-slack-signature": sig}
        with pytest.raises(SlackVerificationError, match="troppo vecchia"):
            verify_slack_request(headers, body)

    def test_missing_headers_raises(self):
        from src.slack_verifier import verify_slack_request, SlackVerificationError
        with pytest.raises(SlackVerificationError, match="mancanti"):
            verify_slack_request({}, '{"type": "message"}')


# ---------------------------------------------------------------------------
# Test: chatbot_client
# ---------------------------------------------------------------------------

class TestDOS68KClient:

    @pytest.mark.asyncio
    async def test_create_session_returns_id(self):
        from src.chatbot_client import DOS68KClient
        client = DOS68KClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "session-123",
            "userId": "user-uuid",
            "title": "Test",
            "createdAt": "2026-04-21T10:00:00",
            "expiresAt": None,
        }

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            session_id = await client.create_session("USLACK123")
            assert session_id == "session-123"

    @pytest.mark.asyncio
    async def test_send_query_returns_answer(self):
        from src.chatbot_client import DOS68KClient
        client = DOS68KClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"answer": "Sono il chatbot DOS68K di PagoPA!"}

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            answer = await client.send_query("USLACK123", "sess-abc", "Chi sei?")
            assert "DOS68K" in answer

    @pytest.mark.asyncio
    async def test_send_query_raises_on_error(self):
        from src.chatbot_client import DOS68KClient, ChatbotAPIError
        client = DOS68KClient()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            with pytest.raises(ChatbotAPIError) as exc_info:
                await client.send_query("USLACK123", "sess-abc", "domanda")
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_session_raises_not_found(self):
        from src.chatbot_client import DOS68KClient, SessionNotFoundError
        client = DOS68KClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
            with pytest.raises(SessionNotFoundError):
                await client.get_session("USLACK123", "sess-nonexistent")


# ---------------------------------------------------------------------------
# Test: logging_config (punto aperto #4)
# ---------------------------------------------------------------------------

class TestHealthCheckFilter:

    def test_health_check_filtered_when_disabled(self, monkeypatch):
        import logging
        monkeypatch.setenv("LOG_HEALTH_CHECKS", "false")
        from src.logging_config import HealthCheckFilter
        f = HealthCheckFilter()
        record = logging.LogRecord(
            name="uvicorn.access", level=logging.INFO,
            pathname="", lineno=0,
            msg="GET /health HTTP/1.1 200", args=(), exc_info=None
        )
        assert f.filter(record) is False

    def test_health_check_allowed_when_enabled(self, monkeypatch):
        import logging
        monkeypatch.setenv("LOG_HEALTH_CHECKS", "true")
        from src.logging_config import HealthCheckFilter
        f = HealthCheckFilter()
        record = logging.LogRecord(
            name="uvicorn.access", level=logging.INFO,
            pathname="", lineno=0,
            msg="GET /health HTTP/1.1 200", args=(), exc_info=None
        )
        assert f.filter(record) is True

    def test_normal_log_always_passes(self, monkeypatch):
        import logging
        monkeypatch.setenv("LOG_HEALTH_CHECKS", "false")
        from src.logging_config import HealthCheckFilter
        f = HealthCheckFilter()
        record = logging.LogRecord(
            name="app", level=logging.INFO,
            pathname="", lineno=0,
            msg="POST /queries/abc 200", args=(), exc_info=None
        )
        assert f.filter(record) is True