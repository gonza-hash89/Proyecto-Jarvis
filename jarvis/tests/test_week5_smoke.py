"""
Smoke test end-to-end de la Semana 5 (FASE 5, verificación)

Ejecuta el flujo completo del Orchestrator (process_input) con los agentes
reales registrados (System, Web, Dialog), mockeando solo los efectos
externos (red, webbrowser, os.startfile, os.system) para que sea
determinista y no toque el sistema real.
"""

import os
import types

import agents.dialog as dialog_mod
import agents.web as web_mod
from agents.dialog import DialogAgent
from agents.factory import AgentFactory
from agents.registry import AgentRegistry
from brain.decision import AgentType, DecisionEngine
from brain.intent_processor import get_processor
from orchestrator.orchestrator import JarvisState, Orchestrator


class _FakeLogger:
    def info(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeErrorHandler:
    def handle(self, **kwargs):
        pass


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeRequests:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(url)
        if "geocoding-api" in url:
            return _FakeResp(
                {
                    "results": [
                        {"name": "Lima", "latitude": -12.05, "longitude": -77.04}
                    ]
                }
            )
        if "api.open-meteo" in url:
            return _FakeResp(
                {
                    "current": {
                        "temperature_2m": 18.0,
                        "relative_humidity_2m": 82,
                        "weather_code": 3,
                    }
                }
            )
        if "coingecko" in url:
            return _FakeResp({"bitcoin": {"usd": 65432.10, "usd_24h_change": 2.5}})
        return _FakeResp({})


class _FakeMemory:
    def __init__(self):
        self.events = []

    async def set_context(self, key, value):
        self.events.append(("set_context", key, value))

    async def save_conversation(self, **kwargs):
        self.events.append(("save", kwargs))


class _Harness:
    def __init__(self, inst, memory, started, syscalls, web_opened, requests):
        self.inst = inst
        self.memory = memory
        self.started = started
        self.syscalls = syscalls
        self.web_opened = web_opened
        self.requests = requests


def _build_harness(monkeypatch, tmp_path):
    requests = _FakeRequests()
    monkeypatch.setattr(web_mod, "requests", requests)

    started = []
    monkeypatch.setattr(os, "startfile", lambda p: started.append(p))
    syscalls = []
    monkeypatch.setattr(os, "system", lambda c: syscalls.append(c))
    web_opened = []
    monkeypatch.setattr(web_mod.webbrowser, "open", lambda url: web_opened.append(url))

    inst = object.__new__(Orchestrator)
    inst.config = types.SimpleNamespace(base_dir=str(tmp_path), data_dir="data")
    inst.state = JarvisState.IDLE
    inst.logger = _FakeLogger()
    inst._publish = lambda event, payload=None, priority=None: None
    inst.speak = lambda text: None
    inst.error_handler = _FakeErrorHandler()
    inst.intent_recognizer = None
    inst._voice_available = False

    memory = _FakeMemory()
    inst.memory = memory
    inst.intent_processor = get_processor()
    inst.decision_engine = DecisionEngine()
    inst.agent_registry = AgentRegistry()
    inst.agent_factory = AgentFactory()

    for agent_type in (AgentType.SYSTEM, AgentType.WEB, AgentType.DIALOG):
        agent = inst.agent_factory.create(agent_type)
        assert agent is not None, f"No se pudo crear {agent_type}"
        inst.agent_registry.register(agent)

    for agent in inst.agent_registry.list_all():
        if isinstance(agent, DialogAgent):
            agent._api_key = ""

    inst.agent_registry.start_all()

    assert inst.agent_registry.get_count() == 3
    return _Harness(inst, memory, started, syscalls, web_opened, requests)


def _say(harness, phrase):
    response = harness.inst.process_input(phrase)
    assert response, f"Sin respuesta del orquestador para: {phrase}"
    return response


# ────────── Escenarios del smoke test ──────────

def test_smoke_clima_en_lima(monkeypatch, tmp_path):
    h = _build_harness(monkeypatch, tmp_path)
    response = _say(h, "qué clima hace en Lima")
    assert "Clima en Lima" in response
    assert "°C" in response
    assert any("geocoding-api" in url for url in h.requests.calls)
    assert any("api.open-meteo" in url for url in h.requests.calls)


def test_smoke_precio_bitcoin(monkeypatch, tmp_path):
    h = _build_harness(monkeypatch, tmp_path)
    response = _say(h, "precio del bitcoin")
    assert "bitcoin" in response
    assert "USD" in response
    assert any("coingecko" in url for url in h.requests.calls)


def test_smoke_abre_google(monkeypatch, tmp_path):
    h = _build_harness(monkeypatch, tmp_path)
    response = _say(h, "abre google")
    assert "Abriendo google" in response
    assert h.web_opened and "google.com" in h.web_opened[0]


def test_smoke_apagar_sistema(monkeypatch, tmp_path):
    h = _build_harness(monkeypatch, tmp_path)
    response = _say(h, "apaga la computadora")
    assert "Apagando" in response
    assert h.syscalls and "shutdown /s" in h.syscalls[-1]


def test_smoke_chiste(monkeypatch, tmp_path):
    h = _build_harness(monkeypatch, tmp_path)
    response = _say(h, "cuéntame un chiste")
    assert response.strip()


def test_smoke_ayuda(monkeypatch, tmp_path):
    h = _build_harness(monkeypatch, tmp_path)
    response = _say(h, "qué puedes hacer")
    assert "puedo hacer" in response
    assert response.count("comando:") >= 20


def test_smoke_agentes_registrados_activos(monkeypatch, tmp_path):
    h = _build_harness(monkeypatch, tmp_path)
    tipos = {a.agent_type for a in h.inst.agent_registry.list()}
    assert tipos == {"system_agent", "web_agent", "dialog_agent"}
    for agent in h.inst.agent_registry.list():
        assert agent.initialized is True


def test_smoke_flujo_completo_guardado(monkeypatch, tmp_path):
    h = _build_harness(monkeypatch, tmp_path)
    _say(h, "qué clima hace en Lima")
    _say(h, "precio del bitcoin")
    saved = [e[1] for e in h.memory.events if e[0] == "save"]
    assert saved
    assert any(kwargs.get("intent") == "weather_query" for kwargs in saved)
    assert any(kwargs.get("intent") == "crypto_price" for kwargs in saved)
    assert h.inst.state == JarvisState.IDLE
