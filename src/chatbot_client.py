"""
Client HTTP per le API DOS68K (chatbot PagoPA).

Questo modulo è l'UNICA interfaccia verso il backend DOS68K.

Endpoint usati:
  POST /sessions                → crea una nuova sessione
  POST /queries/{session_id}    → invia domanda, riceve risposta
  DELETE /sessions/{session_id} → elimina la sessione (comando reset)
  POST /sessions/{session_id}/clear → resetta la storia della sessione

Autenticazione:
  x-api-key    → CHATBOT_API_KEY  (tutte le richieste)
  x-user-id    → UUID derivato dallo slack_user_id (tutte le richieste)
  x-user-role  → valore fisso "user" (tutte le richieste)
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
    """Sessione non trovata o scaduta lato DOS68K."""
    pass


class DOS68KClient:
    """Client asincrono verso le API DOS68K."""

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
        Deriva un UUID stabile dall'ID Slack per l'header x-user-id.
        uuid5 è deterministico: stesso slack_user_id → stesso UUID sempre.
        """
        user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"slack:{slack_user_id}"))
        return {"x-user-id": user_uuid, "x-user-role": "user"}

    async def create_session(self, slack_user_id: str, title: str = "Slack Chat") -> str:
        """Crea una nuova sessione su DOS68K e restituisce il session_id."""
        logger.info(f"Creazione sessione DOS68K per user={self._user_headers(slack_user_id)} title={title}")
        resp = await self._client.post(
            "/sessions",
            json={"title": title, "isTemporary": False},
            headers=self._user_headers(slack_user_id),
        )
        self._raise_for_status(resp)
        session_id = resp.json()["id"]
        logger.info(f"Sessione DOS68K creata: session_id={session_id} user={slack_user_id}")
        return session_id


    async def get_session(self, slack_user_id: str, session_id: str) -> dict:
        """
        Verifica che la sessione esista su DOS68K.
        Usato da `resume` per validare l'ID fornito dall'utente.
        Solleva SessionNotFoundError se la sessione non esiste o è scaduta.
        """
        resp = await self._client.get(
            f"/sessions/{session_id}",
            headers=self._user_headers(slack_user_id),
        )
        if resp.status_code == 404:
            raise SessionNotFoundError(404, f"Sessione {session_id} non trovata")
        self._raise_for_status(resp)
        return resp.json()

    async def list_sessions(self, slack_user_id: str) -> list[dict]:
        """
        Recupera tutte le sessioni dell'utente da DOS68K.
        Usato dal comando `list`.
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
        """Invia una domanda al chatbot e restituisce la risposta testuale."""
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
        """Elimina definitivamente la sessione su DOS68K."""
        resp = await self._client.delete(
            f"/sessions/{session_id}",
            headers=self._user_headers(slack_user_id),
        )
        if resp.status_code == 404:
            logger.warning(f"Sessione {session_id} già assente su DOS68K, ignorato")
            return
        self._raise_for_status(resp)
        logger.info(f"Sessione {session_id} eliminata su DOS68K")

    async def clear_session(self, slack_user_id: str, session_id: str) -> None:
        """Resetta la storia della sessione (mantiene la sessione aperta)."""
        resp = await self._client.post(
            f"/sessions/{session_id}/clear",
            headers=self._user_headers(slack_user_id),
        )
        self._raise_for_status(resp)
        logger.info(f"Sessione {session_id} resettata")

    async def close(self):
        await self._client.aclose()

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise ChatbotAPIError(resp.status_code, resp.text[:500])