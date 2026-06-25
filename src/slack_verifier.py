"""
Verifies the signature of Slack requests.
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
    Verifies that the request genuinely comes from Slack.
    Raises SlackVerificationError if verification fails.
    """
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")

    if not timestamp or not signature:
        raise SlackVerificationError("Missing Slack headers")

    try:
        ts = int(timestamp)
    except ValueError:
        raise SlackVerificationError("Invalid timestamp")

    # Replay attack protection: requests older than 5 minutes are rejected
    if abs(time.time() - ts) > 300:
        raise SlackVerificationError("Request too old (possible replay attack)")

    sig_basestring = f"v0:{timestamp}:{body}"
    expected = "v0=" + hmac.new(
        settings.slack_signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise SlackVerificationError("Invalid Slack signature")
