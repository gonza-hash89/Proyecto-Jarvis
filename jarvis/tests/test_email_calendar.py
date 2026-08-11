"""
test_email_calendar.py - Tests de EmailAgent y CalendarAgent (SEMANA 6, FASE 3)

Verifica:
- Contrato AgentBase (process, mensaje inválido, intención no soportada)
- EmailAgent: credenciales desde config/archivo, lectura IMAP mockeada,
  degradación elegante (sin credenciales, error de conexión, login fallido)
- CalendarAgent: degradación (sin librería, sin token), API mockeada
- Sin llamadas reales de red en ninguna prueba.
"""

import json
from pathlib import Path

import agents.calendar as cal_mod
import agents.email as email_mod
from agents.base import AgentBase
from agents.calendar import CalendarAgent
from agents.email import EmailAgent


# ══════════════════════ DOBLES DE PRUEBA ══════════════════════

class _FakeIMAPConnection:
    """Fake de la conexión imaplib.IMAP4_SSL."""

    def __init__(self, host, raise_on=None):
        self.host = host
        self.logged_in = False
        self.selected = False
        self.closed = False
        self.raise_on = raise_on or []
        self.messages = [
            {
                "from": "ana@test.com",
                "subject": "Hola equipo",
                "date": "Mon, 04 Aug 2026 10:00:00 +0000",
            },
            {
                "from": "=?utf-8?q?Mar=C3=ADa?= <maria@test.com>",
                "subject": "=?utf-8?q?Reuni=C3=B3n?= del lunes",
                "date": "Tue, 05 Aug 2026 09:30:00 +0000",
            },
            {
                "from": "jefe@test.com",
                "subject": "IMPORTANTE: entrega",
                "date": "Wed, 06 Aug 2026 08:00:00 +0000",
            },
        ]

    def login(self, user, pwd):
        if "login" in self.raise_on:
            raise email_mod.imaplib.IMAP4.error("login rechazado")
        self.logged_in = True

    def select(self, folder):
        if "select" in self.raise_on:
            raise ConnectionError("inbox no disponible")
        self.selected = True

    def search(self, *args):
        return ("OK", [b"1 2 3"])

    def fetch(self, msg_id, *args):
        index = int(msg_id) - 1
        raw = (
            f"From: {self.messages[index]['from']}\r\n"
            f"Subject: {self.messages[index]['subject']}\r\n"
            f"Date: {self.messages[index]['date']}\r\n"
            f"\r\ncuerpo\r\n"
        ).encode("utf-8")
        return ("OK", [(b"1", raw)])

    def logout(self):
        self.closed = True


class _FakeIMAPModule:
    """Reemplaza al módulo imaplib con conexiones falsas."""

    def __init__(self, connection=None, connect_error=None):
        self.connection = connection or _FakeIMAPConnection("imaps.test.com")
        self.connect_error = connect_error

    class IMAP4:
        class error(Exception):
            pass

    def IMAP4_SSL(self, host):
        if self.connect_error:
            raise self.connect_error
        return self.connection


# ══════════════════════ HELPERS ══════════════════════

def _email_agent(tmp_path, **cfg):
    base = {"credentials_dir": str(tmp_path)}
    base.update(cfg)
    return EmailAgent("email_agent", base)


def _cal_agent(tmp_path, **cfg):
    base = {"credentials_dir": str(tmp_path)}
    base.update(cfg)
    return CalendarAgent("calendar_agent", base)


def _process(agent, intent, params=None, text=""):
    return agent.process({
        "intent": intent,
        "parameters": params or {},
        "text": text,
    })


# ══════════════════════ CONTRATO BASE ══════════════════════

def test_email_hereda_de_agentbase(tmp_path):
    assert isinstance(_email_agent(tmp_path), AgentBase)


def test_calendar_hereda_de_agentbase(tmp_path):
    assert isinstance(_cal_agent(tmp_path), AgentBase)


def test_email_mensaje_invalido(tmp_path):
    resp = _email_agent(tmp_path).process("hola")
    assert resp["status"] == "error"
    assert resp["agent"] == "email_agent"


def test_calendar_mensaje_invalido(tmp_path):
    resp = _cal_agent(tmp_path).process("hola")
    assert resp["status"] == "error"
    assert resp["agent"] == "calendar_agent"


def test_intencion_no_soportada(tmp_path):
    resp = _process(_email_agent(tmp_path), "intencion_aleatoria")
    assert resp["status"] == "success"
    assert "en desarrollo" in resp["data"]["result"]
    resp = _process(_cal_agent(tmp_path), "intencion_aleatoria")
    assert resp["status"] == "success"
    assert "en desarrollo" in resp["data"]["result"]


def test_get_info_capacidades(tmp_path):
    info = _email_agent(tmp_path).get_info()
    assert "read_emails" in info["capabilities"]
    assert "send_email" in info["capabilities"]
    info = _cal_agent(tmp_path).get_info()
    assert "calendar_event" in info["capabilities"]


# ══════════════════════ EMAIL: CREDENCIALES ══════════════════════

def test_credenciales_desde_config(tmp_path):
    agent = _email_agent(tmp_path, email_user="u@x.com", email_password="pass")
    assert agent.is_configured
    assert agent._user == "u@x.com"


def test_credenciales_desde_archivo(tmp_path):
    cred_file = tmp_path / "email.json"
    cred_file.write_text(json.dumps({"user": "archivo@x.com", "password": "secret"}),
                         encoding="utf-8")
    agent = _email_agent(tmp_path, credentials_file=str(cred_file))
    assert agent.is_configured
    assert agent._user == "archivo@x.com"


def test_sin_credenciales_no_configurado(tmp_path):
    agent = _email_agent(tmp_path)
    assert not agent.is_configured
    resp = _process(agent, "read_emails")
    assert resp["status"] == "success"
    assert resp["data"]["configured"] is False
    assert "no hay credenciales" in resp["data"]["result"].lower()


# ══════════════════════ EMAIL: IMAP ══════════════════════

def test_read_emails_ok(monkeypatch, tmp_path):
    conn = _FakeIMAPConnection("imaps.test.com")
    monkeypatch.setattr(email_mod, "imaplib", _FakeIMAPModule(conn))
    agent = _email_agent(tmp_path, email_user="u@x.com", email_password="pass")

    resp = _process(agent, "read_emails")
    assert resp["status"] == "success"
    data = resp["data"]
    assert len(data["emails"]) == 3
    assert conn.logged_in and conn.selected and conn.closed
    # decode RFC 2047
    assert data["emails"][1]["subject"] == "Reunión del lunes"
    assert data["emails"][1]["from"] == "María <maria@test.com>"
    assert "Hola equipo" in data["result"]


def test_read_emails_limite(monkeypatch, tmp_path):
    monkeypatch.setattr(email_mod, "imaplib", _FakeIMAPModule())
    agent = _email_agent(tmp_path, email_user="u@x.com", email_password="pass")
    resp = _process(agent, "read_emails", {"limit": 2})
    assert len(resp["data"]["emails"]) == 2


def test_read_emails_limite_desde_texto(monkeypatch, tmp_path):
    monkeypatch.setattr(email_mod, "imaplib", _FakeIMAPModule())
    agent = _email_agent(tmp_path, email_user="u@x.com", email_password="pass")
    resp = _process(agent, "read_emails", text="muéstrame 1 email")
    assert len(resp["data"]["emails"]) == 1


def test_read_emails_error_conexion(monkeypatch, tmp_path):
    monkeypatch.setattr(email_mod, "imaplib",
                        _FakeIMAPModule(connect_error=ConnectionError("sin red")))
    agent = _email_agent(tmp_path, email_user="u@x.com", email_password="pass")
    resp = _process(agent, "read_emails")
    assert resp["data"]["configured"] is True
    assert resp["data"]["emails"] == []
    assert "no pude conectar" in resp["data"]["result"].lower()


def test_read_emails_login_fallido(monkeypatch, tmp_path):
    conn = _FakeIMAPConnection("imaps.test.com", raise_on=["login"])
    monkeypatch.setattr(email_mod, "imaplib", _FakeIMAPModule(conn))
    agent = _email_agent(tmp_path, email_user="u@x.com", email_password="mal")
    resp = _process(agent, "read_emails")
    assert resp["data"]["emails"] == []
    assert "no pude conectar" in resp["data"]["result"].lower()


def test_send_email_degrada(tmp_path):
    agent = _email_agent(tmp_path)
    resp = _process(agent, "send_email")
    assert resp["status"] == "success"
    assert resp["data"]["enabled"] is False


def test_error_de_parseo_limit(tmp_path):
    agent = _email_agent(tmp_path)
    assert agent._parse_limit("abc", "") == 5
    assert agent._parse_limit("99", "") == 20
    assert agent._parse_limit(0, "") == 1


# ══════════════════════ CALENDAR: DEGRADACIÓN ══════════════════════

def test_calendar_sin_libreria(monkeypatch, tmp_path):
    monkeypatch.setattr(cal_mod, "_GOOGLE_AVAILABLE", False)
    agent = _cal_agent(tmp_path)
    resp = _process(agent, "calendar_event")
    assert resp["data"]["configured"] is False
    assert "google" in resp["data"]["result"].lower()


def test_calendar_sin_token(monkeypatch, tmp_path):
    monkeypatch.setattr(cal_mod, "_GOOGLE_AVAILABLE", True)
    agent = _cal_agent(tmp_path)
    assert not agent.is_configured
    resp = _process(agent, "calendar_event")
    assert resp["data"]["configured"] is False
    assert "no configurado" in resp["data"]["result"].lower()


def test_calendar_token_pero_sin_api(monkeypatch, tmp_path):
    cal_mod.CalendarAgent.write_fake_token(tmp_path / "calendar_token.json")
    monkeypatch.setattr(cal_mod, "_GOOGLE_AVAILABLE", False)
    agent = _cal_agent(tmp_path)
    resp = _process(agent, "calendar_event")
    assert resp["data"]["configured"] is False
    assert "pip install" in resp["data"]["result"].lower()


# ══════════════════════ CALENDAR: API MOCKEADA ══════════════════════

def test_calendar_event_ok(monkeypatch, tmp_path):
    cal_mod.CalendarAgent.write_fake_token(tmp_path / "calendar_token.json")
    monkeypatch.setattr(cal_mod, "_GOOGLE_AVAILABLE", True)

    calls = {"list": 0}

    class _FakeCreds:
        expired = False
        refresh_token = None

        @staticmethod
        def from_authorized_user_file(path, scopes):
            return _FakeCreds()

    class _FakeEvents:
        def list(self, **kwargs):
            calls["list"] += 1
            return self

        def execute(self):
            return {
                "items": [
                    {"summary": "Reunión semanal",
                     "start": {"dateTime": "2026-08-10T09:00:00Z"}},
                    {"summary": "Llamada con cliente",
                     "start": {"dateTime": "2026-08-11T15:30:00Z"}},
                ]
            }

    class _FakeService:
        def events(self):
            return _FakeEvents()

    class _FakeBuild:
        @staticmethod
        def build(*args, **kwargs):
            return _FakeService()

    monkeypatch.setattr(cal_mod, "Credentials", _FakeCreds)
    monkeypatch.setattr(cal_mod, "Request", lambda: None)
    monkeypatch.setattr(cal_mod, "build", _FakeBuild.build)

    agent = _cal_agent(tmp_path)
    assert agent.is_configured
    resp = _process(agent, "calendar_event")
    assert resp["status"] == "success"
    data = resp["data"]
    assert len(data["events"]) == 2
    assert data["events"][0]["summary"] == "Reunión semanal"
    assert "Tus próximos eventos" in data["result"]
    assert calls["list"] == 1


def test_calendar_event_con_refresh(monkeypatch, tmp_path):
    cal_mod.CalendarAgent.write_fake_token(tmp_path / "calendar_token.json")
    monkeypatch.setattr(cal_mod, "_GOOGLE_AVAILABLE", True)
    refreshed = {"called": False}

    class _FakeCreds:
        def __init__(self):
            self.expired = True
            self.refresh_token = "rt"

        @staticmethod
        def from_authorized_user_file(path, scopes):
            return _FakeCreds()

        def refresh(self, request):
            refreshed["called"] = True

    class _FakeEvents:
        def list(self, **kwargs):
            return self

        def execute(self):
            return {"items": []}

    class _FakeService:
        def events(self):
            return _FakeEvents()

    class _FakeBuild:
        @staticmethod
        def build(*args, **kwargs):
            return _FakeService()

    monkeypatch.setattr(cal_mod, "Credentials", _FakeCreds)
    monkeypatch.setattr(cal_mod, "Request", lambda: None)
    monkeypatch.setattr(cal_mod, "build", _FakeBuild.build)

    resp = _process(_cal_agent(tmp_path), "calendar_event")
    assert resp["data"]["events"] == []
    assert "no tienes eventos" in resp["data"]["result"].lower()
    assert refreshed["called"] is True


def test_calendar_event_error_api(monkeypatch, tmp_path):
    cal_mod.CalendarAgent.write_fake_token(tmp_path / "calendar_token.json")
    monkeypatch.setattr(cal_mod, "_GOOGLE_AVAILABLE", True)

    class _FakeBuild:
        @staticmethod
        def build(*args, **kwargs):
            raise RuntimeError("API caída")

    monkeypatch.setattr(cal_mod, "build", _FakeBuild.build)
    resp = _process(_cal_agent(tmp_path), "calendar_event")
    assert resp["data"]["configured"] is True
    assert resp["data"]["events"] == []
    assert "no pude consultar" in resp["data"]["result"].lower()


def test_calendar_max_events_default(tmp_path):
    agent = _cal_agent(tmp_path)
    assert agent._parse_max(None, "") == 5
    assert agent._parse_max("3", "") == 3
    assert agent._parse_max("abc", "") == 5
    assert agent._parse_max("99", "") == 20
