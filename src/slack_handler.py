"""
Orchestratore principale degli eventi Slack.

Flusso per ogni messaggio ricevuto:
  1. Verifica firma Slack (HMAC-SHA256)
  2. Gestione URL verification challenge (primo setup Slack App)
  3. Filtra bot messages ed eventi irrilevanti
  4. Interpreta il comando o il messaggio:
       - Primo messaggio / nessuna sessione attiva → POST /sessions (nuova sessione)
       - Messaggio normale → POST /queries/{session_id} sulla sessione attiva
       - new            → POST /sessions, imposta come sessione attiva
       - list           → GET /sessions/all, mostra elenco con ID
       - resume <id>    → GET /sessions/{id} verifica esistenza, imposta come attiva
       - help           → mostra i comandi disponibili
  5. Risponde nel canale Slack

Gestione sessione attiva:
  Il mapping slack_user_id → session_id attiva è tenuto in un dizionario
  in memoria (_active_sessions). Non persiste al riavvio del container:
  in quel caso l'utente può usare `list` + `resume <id>` per riprendere
  una sessione esistente su DOS68K.
"""

import json
import logging
from typing import Tuple

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

from src.config import settings
from src.slack_verifier import verify_slack_request, SlackVerificationError
from src.chatbot_client import DOS68KClient, ChatbotAPIError, SessionNotFoundError

logger = logging.getLogger(__name__)

# Mapping in memoria: slack_user_id → session_id attiva
# Nota: non persiste al riavvio del container.
_active_sessions: dict[str, str] = {}

HELP_TEXT = """*DOS68K Slack Bot* – Comandi disponibili:
• `new` – Crea una nuova sessione e la imposta come attiva
• `list` – Mostra le sessioni esistenti con i loro ID
• `resume <id>` – Riprende una sessione precedente
• `help` – Mostra questo messaggio

Qualsiasi altro testo viene inviato come domanda al chatbot nella sessione attiva.
Se non c'è una sessione attiva, viene creata automaticamente.
"""


class SlackHandler:
    def __init__(self):
        self._slack = AsyncWebClient(token=settings.slack_bot_token)
        self._chatbot = DOS68KClient()

    async def handle(self, headers: dict, body_str: str) -> Tuple[str, int]:
        """Entry point. Slack richiede risposta HTTP entro 3 secondi."""
        try:
            verify_slack_request(headers, body_str)
        except SlackVerificationError as e:
            logger.warning(f"Verifica firma fallita: {e}")
            return json.dumps({"error": "Forbidden"}), 403

        body = json.loads(body_str)

        if body.get("type") == "url_verification":
            logger.info("Slack URL verification challenge ricevuto")
            return json.dumps({"challenge": body["challenge"]}), 200

        event = body.get("event", {})
        event_type = event.get("type", "")

        if event_type == "message":
            await self._handle_message(event)
        elif event_type == "app_mention":
            await self._handle_message(event, strip_mention=True)
        else:
            logger.debug(f"Evento ignorato: {event_type}")

        return json.dumps({"ok": True}), 200

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

    # ------------------------------------------------------------------
    # Comandi
    # ------------------------------------------------------------------

    async def _cmd_new(self, user_id: str, channel_id: str) -> None:
        """Crea una nuova sessione e la imposta come attiva."""
        try:
            session_id = await self._chatbot.create_session(
                slack_user_id=user_id,
                title=f"Slack – {user_id}",
            )
            _active_sessions[user_id] = session_id
            await self._post(
                channel_id,
                f"✅ Nuova sessione creata e impostata come attiva.\n"
                f"ID: `{session_id}`",
            )
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Errore nella creazione della sessione (HTTP {e.status_code}).")

    async def _cmd_list(self, user_id: str, channel_id: str) -> None:
        """Recupera e mostra tutte le sessioni dell'utente tramite GET /sessions/all."""
        try:
            sessions = await self._chatbot.list_sessions(user_id)
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Errore nel recupero delle sessioni (HTTP {e.status_code}).")
            return

        if not sessions:
            await self._post(channel_id, "Non hai sessioni precedenti. Usa `new` per iniziare.")
            return

        active_id = _active_sessions.get(user_id)
        lines = ["*Le tue sessioni:*"]
        for s in sessions:
            sid = s.get("id", "?")
            title = s.get("title", "—")
            created = s.get("createdAt", "")[:10]  # solo la data
            marker = " ◀ *attiva*" if sid == active_id else ""
            lines.append(f"• `{sid}` – _{title}_ ({created}){marker}")

        lines.append("\nUsa `resume <id>` per riprendere una sessione.")
        await self._post(channel_id, "\n".join(lines))

    async def _cmd_resume(self, user_id: str, channel_id: str, session_id: str) -> None:
        """Verifica che la sessione esista su DOS68K e la imposta come attiva."""
        if not session_id:
            await self._post(channel_id, "Uso corretto: `resume <id>`")
            return

        try:
            await self._chatbot.get_session(user_id, session_id)
            _active_sessions[user_id] = session_id
            await self._post(channel_id, f"✅ Sessione `{session_id}` ripresa. Puoi continuare a scrivere.")
        except SessionNotFoundError:
            await self._post(channel_id, f"⚠️ Sessione `{session_id}` non trovata o scaduta. Usa `list` per vedere le sessioni disponibili.")
        except ChatbotAPIError as e:
            await self._post(channel_id, f"⚠️ Errore nella verifica della sessione (HTTP {e.status_code}).")

    async def _cmd_query(self, user_id: str, channel_id: str, text: str) -> None:
        """
        Invia la query al chatbot sulla sessione attiva.
        Se non c'è una sessione attiva, ne crea una nuova automaticamente.
        """
        session_id = _active_sessions.get(user_id)

        if not session_id:
            # Nessuna sessione attiva: crea automaticamente
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

        try:
            answer = await self._chatbot.send_query(user_id, session_id, text)
            await self._post(channel_id, answer)

        except SessionNotFoundError:
            # La sessione attiva è scaduta su DOS68K: ricrea e riprova
            logger.warning(f"Sessione {session_id} scaduta, ricreazione automatica...")
            _active_sessions.pop(user_id, None)
            try:
                session_id = await self._chatbot.create_session(
                    slack_user_id=user_id,
                    title=f"Slack – {user_id}",
                )
                _active_sessions[user_id] = session_id
                answer = await self._chatbot.send_query(user_id, session_id, text)
                await self._post(channel_id, answer)
            except ChatbotAPIError as e:
                await self._post(channel_id, f"⚠️ Errore (HTTP {e.status_code}). Riprova tra poco.")

        except ChatbotAPIError as e:
            logger.error(f"Errore API DOS68K: {e}")
            await self._post(
                channel_id,
                f"⚠️ Errore nel contattare il chatbot (HTTP {e.status_code}). Riprova tra poco.",
            )
        except Exception as e:
            logger.error(f"Errore imprevisto: {e}", exc_info=True)
            await self._post(channel_id, "⚠️ Si è verificato un errore imprevisto. Riprova tra poco.")

    async def _post(self, channel: str, text: str) -> None:
        try:
            await self._slack.chat_postMessage(channel=channel, text=text)
        except SlackApiError as e:
            logger.error(f"Errore invio messaggio Slack: {e}")