"""
Verifica la firma delle richieste Slack.
https://api.slack.com/authentication/verifying-requests-from-slack
"""

import hashlib
import hmac
import time
import logging

from src.config import settings

logger = logging.getLogger(__name__)


class SlackVerificationError(Exception):
    pass


def verify_slack_request(headers: dict, body: str) -> None:
    """
    Verifica che la richiesta provenga realmente da Slack.
    Solleva SlackVerificationError se la verifica fallisce.
    """
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")

    if not timestamp or not signature:
        raise SlackVerificationError("Header Slack mancanti")

    try:
        ts = int(timestamp)
    except ValueError:
        raise SlackVerificationError("Timestamp non valido")

    # Protegge da replay attack: richieste più vecchie di 5 minuti vengono rifiutate
    if abs(time.time() - ts) > 300:
        raise SlackVerificationError("Request troppo vecchia (possibile replay attack)")

    sig_basestring = f"v0:{timestamp}:{body}"
    expected = "v0=" + hmac.new(
        settings.slack_signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise SlackVerificationError("Firma Slack non valida")