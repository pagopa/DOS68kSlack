"""
Orchestratore principale degli eventi Slack.

Flusso per ogni messaggio ricevuto:
  1. ack()     → verifica firma + gestisce challenge, risponde entro 3s
  2. process() → elaborazione in background (crea sessione, invia query, risponde)

Deduplicazione:
  Slack può reinviare lo stesso evento se non riceve risposta entro 3s.
  Teniamo in memoria gli event_id già processati (con TTL di 5 minuti)
  per ignorare i duplicati.

Gestione sessione attiva:
  Il mapping slack_user_id → session_id attiva è tenuto in un dizionario
  in memoria (_active_sessions). Non persiste al riavvio del container.
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

# Mapping in memoria: slack_user_id → session_id attiva
_active_sessions: dict[str, str] = {}

# Cache event_id già processati: event_id → timestamp
# Previene la doppia elaborazione dei retry di Slack
_processed_events: dict[str, float] = {}
_EVENT_TTL = 300  # 5 minuti


HELP_TEXT = """*DOS68K Slack Bot* – Comandi disponibili:
• `new` – Crea una nuova sessione e la imposta come attiva
• `list` – Mostra le sessioni esistenti con i loro ID
• `resume <id>` – Riprende una sessione precedente
• `help` – Mostra questo messaggio

Qualsiasi altro testo viene inviato come domanda al chatbot nella sessione attiva.
Se non c'è una sessione attiva, viene creata automaticamente.
"""


def _is_duplicate(event_id: str) -> bool:
    """Restituisce True se l'evento è già stato processato."""
    now = time.time()
    # Pulizia entries scadute
    expired = [k for k, v in _processed_events.items() if now - v > _EVENT_TTL]
    for k in expired:
        del _processed_events[k]

    if event_id in _processed_events:
        logger.info(f"Evento duplicato ignorato: {event_id}")
        return True

    _processed_events[event_id] = now
    return False


class SlackHandler:
    def __init__(self):
        self._slack = AsyncWebClient(token=settings.slack_bot_token)
        self._chatbot = DOS68KClient()

    async def ack(self, headers: dict, body_str: str) -> Tuple[str | None, int]:
        """
        Verifica la firma e gestisce i casi che richiedono risposta sincrona.
        Restituisce (response_body, status_code) se deve rispondere direttamente,
        oppure (None, 200) se l'evento va processato in background.
        """
        try:
            verify_slack_request(headers, body_str)
        except SlackVerificationError as e:
            logger.warning(f"Verifica firma fallita: {e}")
            return json.dumps({"error": "Forbidden"}), 403

        body = json.loads(body_str)

        # URL verification challenge (primo setup Slack App) — risposta sincrona obbligatoria
        if body.get("type") == "url_verification":
            logger.info("Slack URL verification challenge ricevuto")
            return json.dumps({"challenge": body["challenge"]}), 200

        return None, 200

    async def process(self, headers: dict, body_str: str) -> None:
        """
        Elaborazione asincrona dell'evento (eseguita in background).
        Gestisce la deduplicazione e instrada al metodo corretto.
        """
        body = json.loads(body_str)
        event_id = body.get("event_id", "")

        # Deduplicazione: ignora i retry di Slack
        if event_id and _is_duplicate(event_id):
            return

        event = body.get("event", {})
        event_type = event.get("type", "")

        if event_type == "message":
            # Risponde solo ai messaggi diretti (DM), non a quelli nei canali.
            # Nei canali risponde esclusivamente tramite app_mention (@Discovery68k).
            # channel_type="im" = DM, "group" = canale privato, "channel" = pubblico.
            channel_type = event.get("channel_type", "")
            if channel_type == "im":
                await self._handle_message(event)
            else:
                logger.debug("Messaggio in canale ignorato (usa @Discovery68k per interagire)")
        elif event_type == "app_mention":
            await self._handle_message(event, strip_mention=True)
        else:
            logger.debug(f"Evento ignorato: {event_type}")

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
                f"✅ Nuova sessione creata e impostata come attiva.\nID: `{session_id}`",
            )
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Errore nella creazione della sessione (HTTP {e.status_code}).")

    async def _cmd_list(self, user_id: str, channel_id: str) -> None:
        try:
            sessions = await self._chatbot.list_sessions(user_id)
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Errore nel recupero delle sessioni (HTTP {e.status_code}).")
            return

        if not sessions:
            await self._post(channel_id, "Non hai sessioni precedenti. Usa `new` per iniziarne una.")
            return

        active_id = _active_sessions.get(user_id)
        lines = ["*Le tue sessioni:*"]
        for s in sessions:
            sid = s.get("id", "?")
            title = s.get("title", "—")
            created = s.get("createdAt", "")[:10]
            marker = " ◀ *attiva*" if sid == active_id else ""
            lines.append(f"• `{sid}` – _{title}_ ({created}){marker}")
        lines.append("\nUsa `resume <id>` per riprendere una sessione.")
        await self._post(channel_id, "\n".join(lines))

    async def _cmd_resume(self, user_id: str, channel_id: str, session_id: str) -> None:
        if not session_id:
            await self._post(channel_id, "Uso corretto: `resume <id>`")
            return
        try:
            await self._chatbot.get_session(user_id, session_id)
            _active_sessions[user_id] = session_id
            await self._post(channel_id, f"✅ Sessione `{session_id}` ripresa. Puoi continuare a scrivere.")
        except SessionNotFoundError:
            await self._post(channel_id, f"⚠️ Sessione `{session_id}` non trovata. Usa `list` per vedere le sessioni disponibili.")
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Errore nella verifica della sessione (HTTP {e.status_code}).")

    async def _cmd_query(self, user_id: str, channel_id: str, text: str) -> None:
        session_id = _active_sessions.get(user_id)

        if not session_id:
            try:
                session_id = await self._chatbot.create_session(
                    slack_user_id=user_id,
                    title=f"Slack – {user_id}",
                )
                _active_sessions[user_id] = session_id
                logger.info(f"Sessione creata automaticamente: {session_id} per utente {user_id}")
            except ChatbotAPIError as e:
                await self._post(channel_id, f"⚠️ Errore nella creazione della sessione (HTTP {e.status_code}).")
                return

        # Mostra subito il placeholder "sta scrivendo"
        placeholder_ts = await self._post_thinking(channel_id)

        try:
            answer = await self._chatbot.send_query(user_id, session_id, text)
            await self._update_or_post(channel_id, placeholder_ts, answer)

        except SessionNotFoundError:
            logger.warning(f"Sessione {session_id} scaduta, ricreazione automatica...")
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
                await self._update_or_post(channel_id, placeholder_ts, f"⚠️ Errore (HTTP {e.status_code}). Riprova tra poco.")

        except ChatbotAPIError as e:
            logger.error(f"Errore API DOS68K: {e}")
            await self._update_or_post(
                channel_id, placeholder_ts,
                f"⚠️ Errore nel contattare il chatbot (HTTP {e.status_code}). Riprova tra poco.",
            )
        except Exception as e:
            logger.error(f"Errore imprevisto: {e}", exc_info=True)
            await self._update_or_post(channel_id, placeholder_ts, "⚠️ Si è verificato un errore imprevisto. Riprova tra poco.")

    async def _post_thinking(self, channel: str) -> str | None:
        """
        Invia un messaggio placeholder visibile mentre il chatbot elabora.
        Restituisce il timestamp del messaggio (usato per aggiornarlo dopo).
        """
        try:
            resp = await self._slack.chat_postMessage(
                channel=channel,
                text="_⏳ Sto elaborando la tua richiesta..._",
            )
            return resp.get("ts")
        except SlackApiError as e:
            logger.error(f"Errore invio placeholder: {e}")
            return None

    async def _update_or_post(self, channel: str, ts: str | None, text: str) -> None:
        """
        Aggiorna il messaggio placeholder con la risposta finale.
        Se per qualsiasi motivo il timestamp non è disponibile, invia un nuovo messaggio.
        """
        if ts:
            try:
                await self._slack.chat_update(channel=channel, ts=ts, text=text)
                return
            except SlackApiError as e:
                logger.warning(f"Impossibile aggiornare il messaggio ({e}), invio nuovo messaggio")
        # Fallback: nuovo messaggio
        await self._post(channel, text)

    async def _post(self, channel: str, text: str) -> None:
        try:
            await self._slack.chat_postMessage(channel=channel, text=text)
        except SlackApiError as e:
            logger.error(f"Errore invio messaggio Slack: {e}")
