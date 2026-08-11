"""
agents/email.py - Email Agent (SEMANA 6, FASE 3)

Lee los últimos emails de Gmail vía IMAP (sin key, con app-password).

- read_emails: lista los últimos N emails (remitente, asunto, fecha)
- send_email: en desarrollo / degradación elegante

Credenciales (opcionales):
- Config: email_user, email_password, imap_host
- O bien un archivo JSON de credenciales en credentials_dir
  (default: data/credentials/email.json) con {"user": ..., "password": ...}

Degradación elegante:
- Sin credenciales → mensaje claro, sin excepciones.
- Sin conexión o error IMAP → mensaje de error, el agente sigue vivo.
- Todas las llamadas a imaplib son mockeables en los tests.
"""

import json
import re
from email.header import decode_header, make_header
from typing import Any, Dict, List, Optional
from pathlib import Path

from agents.base import AgentBase

# imaplib y email son stdlib; pero se importan aquí para poder mockearlos
import imaplib
import email as email_lib


class EmailAgent(AgentBase):
    """Agente de correo: lectura de Gmail vía IMAP con degradación elegante."""

    def __init__(
        self,
        agent_type: str = "email_agent",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=agent_type, agent_type=agent_type, config=config)
        cfg = config or {}
        self.imap_host: str = cfg.get("imap_host", "imaps.google.com")
        self.credentials_dir: Path = Path(cfg.get("credentials_dir") or "data/credentials")
        self._user, self._password = self._load_credentials(cfg)
        self._handlers: Dict[str, Any] = {
            "read_emails": self._read_emails,
            "send_email": self._send_email,
        }

    # ==================== CREDENCIALES ====================

    def _load_credentials(self, cfg: Dict[str, Any]) -> tuple:
        """Carga credenciales desde config o desde archivo JSON."""
        user = cfg.get("email_user") or ""
        password = cfg.get("email_password") or ""
        if user and password:
            return user, password

        cred_file = cfg.get("credentials_file")
        if not cred_file:
            cred_file = self.credentials_dir / "email.json"
        try:
            if Path(cred_file).is_file():
                with open(cred_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("user", ""), data.get("password", "")
        except Exception as e:  # pragma: no cover - archivo corrupto
            self.record_error("load_credentials", e)
        return "", ""

    @property
    def is_configured(self) -> bool:
        """True si hay credenciales para conectar a IMAP."""
        return bool(self._user and self._password)

    # ==================== PUNTO DE ENTRADA ====================

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un mensaje y resuelve la operación de correo."""
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
        info["configured"] = self.is_configured
        info["imap_host"] = self.imap_host
        return info

    # ==================== LECTURA DE EMAILS ====================

    def _read_emails(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Lista los últimos emails del inbox."""
        if not self.is_configured:
            return {
                "result": "No hay credenciales de correo configuradas.",
                "configured": False,
                "emails": [],
            }

        limit = self._parse_limit(params.get("limit"), user_input)
        emails = self._fetch_recent(limit)
        if emails is None:
            return {
                "result": "No pude conectar con el servidor de correo.",
                "configured": True,
                "emails": [],
            }
        if not emails:
            return {"result": "Tu bandeja de entrada está vacía.", "emails": []}

        lines = "\n".join(
            f"- {e['date']} · {e['from']}: {e['subject']}" for e in emails
        )
        return {"result": f"Tus últimos {len(emails)} emails:\n{lines}", "emails": emails}

    def _fetch_recent(self, limit: int) -> Optional[List[Dict[str, Any]]]:
        """Conecta por IMAP y devuelve los últimos `limit` emails."""
        try:
            mail = imaplib.IMAP4_SSL(self.imap_host)
        except Exception as e:
            self.record_error("imap_connect", e)
            return None
        try:
            try:
                mail.login(self._user, self._password)
            except imaplib.IMAP4.error as e:
                self.record_error("imap_login", e)
                return None

            mail.select("INBOX")
            _, data = mail.search(None, "ALL")
            ids = data[0].split()
            recent_ids = ids[-limit:] if ids else []

            emails: List[Dict[str, Any]] = []
            for msg_id in recent_ids:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                emails.append({
                    "from": self._decode_header(msg.get("From", "")),
                    "subject": self._decode_header(msg.get("Subject", "")),
                    "date": str(msg.get("Date", "")),
                })
            return emails
        except Exception as e:
            self.record_error("imap_fetch", e)
            return None
        finally:
            try:
                mail.logout()
            except Exception:  # pragma: no cover - ya cerrado
                pass

    def _send_email(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Envío de email: degradación elegante (en desarrollo)."""
        return {
            "result": "Aún no puedo enviar emails; puedo leer tu bandeja de entrada.",
            "enabled": False,
        }

    # ==================== UTILIDADES ====================

    @staticmethod
    def _parse_limit(raw: Any, user_input: str) -> int:
        """Extrae un límite de número de emails (1-20, default 5)."""
        limit = 5
        if raw is not None and raw != "":
            try:
                limit = int(raw)
            except (TypeError, ValueError):
                pass
        if not raw:
            match = re.search(r"(\d+)\s*(emails?|correos?|mails?)", user_input, re.IGNORECASE)
            if match:
                limit = int(match.group(1))
        return max(1, min(limit, 20))

    @staticmethod
    def _decode_header(raw: str) -> str:
        """Decodifica un header de email (RFC 2047) de forma segura."""
        if not raw:
            return ""
        try:
            return str(make_header(decode_header(raw)))
        except Exception:  # pragma: no cover - encoding raro
            return raw

    @staticmethod
    def _result(status: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la respuesta estándar del agente."""
        return {"status": status, "data": data, "agent": "email_agent"}
