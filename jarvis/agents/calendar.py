"""
agents/calendar.py - Calendar Agent (SEMANA 6, FASE 3)

Próximos eventos del Google Calendar con degradación elegante:
- calendar_event: lista los próximos eventos del calendario principal.

Credenciales (opcionales):
- token OAuth en credentials_dir (default: data/credentials/calendar_token.json)
  generado con el flujo estándar de Google (pip install google-api-python-client
  google-auth-httplib2 google-auth-oauthlib).

Degradación elegante:
- Sin google-api-python-client instalado → mensaje claro, sin excepciones.
- Sin token OAuth → "Calendario no configurado", sin fallar.
- Error de red/API → mensaje de error, el agente sigue vivo.
- Todas las llamadas a la API son mockeables en los tests.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from pathlib import Path

from agents.base import AgentBase

# Librerías de Google (opcionales): si no están, degradamos elegantemente.
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    _GOOGLE_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin google-api-python-client
    Credentials = None
    Request = None
    build = None
    _GOOGLE_AVAILABLE = False

# Descargable para pruebas: credencial OAuth falsa sin token real
_FAKE_TOKEN = {"token": "fake", "refresh_token": "fake", "client_id": "fake",
               "token_uri": "https://oauth2.googleapis.com/token",
               "scopes": ["https://www.googleapis.com/auth/calendar.readonly"]}


class CalendarAgent(AgentBase):
    """Agente de calendario: próximos eventos con degradación elegante."""

    def __init__(
        self,
        agent_type: str = "calendar_agent",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=agent_type, agent_type=agent_type, config=config)
        cfg = config or {}
        self.credentials_dir: Path = Path(cfg.get("credentials_dir") or "data/credentials")
        self.max_events: int = int(cfg.get("max_events") or 5)
        self._handlers: Dict[str, Any] = {
            "calendar_event": self._calendar_event,
        }

    # ==================== PUNTO DE ENTRADA ====================

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un mensaje y resuelve la operación de calendario."""
        if not isinstance(message, dict):
            return self._result(
                "error", {"result": "Mensaje inválido", "source": "internal"}
            )

        intent = message.get("intent") or message.get("name") or ""
        params = message.get("parameters") or message.get("entities") or {}
        if not isinstance(params, dict):
            params = {}
        user_input = (
            message.get("text")
            or message.get("user_input")
            or message.get("input")
            or ""
        )

        handler = self._handlers.get(intent)
        if handler is None:
            return self._result(
                "success",
                {"result": f"Intención '{intent}' en desarrollo", "source": "internal"},
            )

        try:
            data = handler(params, user_input)
            return self._result("success", data)
        except Exception as e:
            self.record_error(f"process:{intent}", e)
            return self._result(
                "error", {"intent": intent, "error": str(e), "source": "internal"}
            )

    def handle_event(self, event: Dict[str, Any]) -> None:
        """Reacciona a eventos del bus (por ahora solo registra)."""
        self.logger.debug(f"Evento recibido: {event}")

    def get_info(self) -> Dict[str, Any]:
        """Información del agente más sus capacidades y estado."""
        info = super().get_info()
        info["capabilities"] = list(self._handlers.keys())
        info["google_api"] = _GOOGLE_AVAILABLE
        info["token_file"] = str(self._token_path())
        info["configured"] = self.is_configured
        return info

    @property
    def is_configured(self) -> bool:
        """True si google-api-python-client está y existe token OAuth."""
        return _GOOGLE_AVAILABLE and self._token_path().is_file()

    # ==================== CALENDARIO ====================

    def _calendar_event(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Devuelve los próximos eventos del calendario principal."""
        if not _GOOGLE_AVAILABLE:
            return {
                "result": "No tengo el módulo de Google Calendar instalado "
                          "(pip install google-api-python-client).",
                "configured": False,
                "events": [],
            }

        if not self._token_path().is_file():
            return {
                "result": "Calendario no configurado: falta el token OAuth en "
                          f"{self._token_path()}.",
                "configured": False,
                "events": [],
            }

        max_results = self._parse_max(params.get("limit"), user_input)
        events = self._fetch_events(max_results)
        if events is None:
            return {
                "result": "No pude consultar tu calendario (revisa el token o la red).",
                "configured": True,
                "events": [],
            }
        if not events:
            return {"result": "No tienes eventos próximos.", "events": []}

        lines = "\n".join(
            f"- {e['start']} · {e['summary']}" for e in events
        )
        return {"result": f"Tus próximos eventos:\n{lines}", "events": events}

    def _fetch_events(self, max_results: int) -> Optional[list]:
        """Llama a la API de Google Calendar y devuelve los eventos."""
        try:
            creds = Credentials.from_authorized_user_file(
                str(self._token_path()), ["https://www.googleapis.com/auth/calendar.readonly"]
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())

            service = build("calendar", "v3", credentials=creds)
            now = datetime.now(timezone.utc).isoformat()
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=now,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = []
            for item in result.get("items", []):
                start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
                events.append({"summary": item.get("summary", ""), "start": start})
            return events
        except Exception as e:
            self.record_error("calendar_fetch", e)
            return None

    # ==================== UTILIDADES ====================

    def _token_path(self) -> Path:
        """Ruta del token OAuth de Google Calendar."""
        return self.credentials_dir / "calendar_token.json"

    def _parse_max(self, raw: Any, user_input: str) -> int:
        """Extrae un límite de eventos (1-20, default config)."""
        try:
            if raw:
                return max(1, min(int(raw), 20))
        except (TypeError, ValueError):
            pass
        return max(1, min(self.max_events, 20))

    @staticmethod
    def _result(status: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la respuesta estándar del agente."""
        return {"status": status, "data": data, "agent": "calendar_agent"}

    # ───────────── helpers públicos para tests / setup ─────────────

    @classmethod
    def write_fake_token(cls, path: Path) -> None:
        """Escribe un token OAuth de prueba en `path` (sin credenciales reales)."""
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_FAKE_TOKEN), encoding="utf-8")
