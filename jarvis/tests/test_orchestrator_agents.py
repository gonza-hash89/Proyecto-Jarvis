"""
test_orchestrator_agents.py - Integración orquestador → agentes (SEMANA 5, FASE 4)

Verifica que _execute_intent() delega en los agentes según AgentType:
- Inicialización de los 3 agentes (System, Web, Dialog) con event_bus
- Delegación correcta por AgentType y por ruteo de intenciones
- Fallback elegante cuando el agente no existe, no maneja la intención
  o falla durante el procesamiento
"""

import types

from orchestrator.orchestrator import JarvisState, Orchestrator
from agents.registry import AgentRegistry
from brain.decision import AgentType


# ==================== DOBLES DE PRUEBA ====================

class _FakeAgent:
    def __init__(self, agent_type, handlers):
        self.name = agent_type
        self.agent_type = agent_type
        self.is_active = True
        self.initialized = True
        self.event_bus = None
        self._handlers = handlers
        self.calls = []

    def process(self, message):
        self.calls.append(message)
        return {
            "status": "success",
            "data": {"result": f"ok:{message['intent']}"},
            "agent": self.agent_type,
        }


class _FailingAgent(_FakeAgent):
    def process(self, message):
        self.calls.append(message)
        return {"status": "error", "data": {"error": "boom"}}


class _RaisingAgent(_FakeAgent):
    def process(self, message):
        self.calls.append(message)
        raise RuntimeError("boom")


class _FakeDecisionEngine:
    def __init__(self, agent_type):
        self._type = agent_type

    def decide(self, intents):
        return types.SimpleNamespace(selected_agent=self._type)


def _intent(name, params=None, confidence=0.9):
    return types.SimpleNamespace(
        name=name,
        confidence=confidence,
        parameters=params or {},
        raw_text=name,
    )


def _make_stub():
    """Instancia de Orchestrator sin __init__ (evita voz/memoria)."""
    inst = object.__new__(Orchestrator)
    inst.config = types.SimpleNamespace(
        base_dir=".",
        data_dir="data",
        system=types.SimpleNamespace(name="Jarvis", version="0.1.0"),
    )
    inst.speak = lambda text: None
    inst._publish = lambda *a, **k: None
    inst.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    inst.engine = None
    inst._voice_available = False
    inst.is_running = True
    return inst


# ────────── Inicialización de agentes ──────────

def test_inicializa_tres_agentes():
    inst = _make_stub()
    bus = object()
    inst.event_bus = bus
    inst._init_agents()

    assert inst.agent_registry.get_count() == 3
    types_set = {a.agent_type for a in inst.agent_registry.list_all()}
    assert types_set == {"system_agent", "web_agent", "dialog_agent"}
    assert all(a.event_bus is bus for a in inst.agent_registry.list_all())
    assert all(getattr(a, "_handlers", {}) for a in inst.agent_registry.list_all())


# ────────── Delegación por AgentType ──────────

def test_delega_por_agent_type():
    inst = _make_stub()
    web = _FakeAgent("web_agent", {"weather_query": True})
    registry = AgentRegistry()
    registry.register(web)
    inst.agent_registry = registry
    inst.decision_engine = _FakeDecisionEngine(AgentType.WEB)

    resp = inst._execute_intent(_intent("weather_query", {"location": "Lima"}), "clima en Lima")

    assert resp == "ok:weather_query"
    assert len(web.calls) == 1

    msg = web.calls[0]
    assert msg["intent"] == "weather_query"
    assert msg["entities"] == {"location": "Lima"}
    assert msg["raw_input"] == "clima en Lima"
    assert msg["confidence"] == 0.9
    assert msg["text"] == "clima en Lima"


def test_routing_override_manda_al_agente_correcto():
    inst = _make_stub()
    web = _FakeAgent("web_agent", {"weather_query": True})
    dialog = _FakeAgent("dialog_agent", {"smalltalk": True})
    registry = AgentRegistry()
    registry.register(web)
    registry.register(dialog)
    inst.agent_registry = registry
    # El DecisionEngine real mapea por defecto a DIALOG; el ruteo del
    # orquestador debe redirigir weather_query al Web Agent.
    inst.decision_engine = _FakeDecisionEngine(AgentType.DIALOG)

    resp = inst._execute_intent(_intent("weather_query", {}), "clima en Lima")

    assert resp == "ok:weather_query"
    assert len(web.calls) == 1
    assert len(dialog.calls) == 0


def test_delega_dialog_agent():
    inst = _make_stub()
    dialog = _FakeAgent("dialog_agent", {"smalltalk": True})
    registry = AgentRegistry()
    registry.register(dialog)
    inst.agent_registry = registry
    inst.decision_engine = _FakeDecisionEngine(AgentType.DIALOG)

    resp = inst._execute_intent(_intent("smalltalk", {}), "hola")

    assert resp == "ok:smalltalk"
    assert len(dialog.calls) == 1


# ────────── Fallback cuando no hay agente ──────────

def test_fallback_cuando_agente_no_disponible():
    inst = _make_stub()
    web = _FakeAgent("web_agent", {"weather_query": True})
    registry = AgentRegistry()
    registry.register(web)
    inst.agent_registry = registry
    inst.decision_engine = _FakeDecisionEngine(AgentType.SYSTEM)  # no existe

    resp = inst._execute_intent(_intent("reminder_set", {}), "recuerdame comprar leche")

    assert resp is not None
    assert "no tengo implementada" in resp
    assert len(web.calls) == 0


def test_agente_sin_handler_usa_fallback():
    inst = _make_stub()
    sys_agent = _FakeAgent("system_agent", {"system_control": True})
    registry = AgentRegistry()
    registry.register(sys_agent)
    inst.agent_registry = registry
    inst.decision_engine = _FakeDecisionEngine(AgentType.SYSTEM)

    # time_query se rutea a SYSTEM, pero el System Agent no la maneja:
    # debe caer a la acción directa _action_time (las 23 siguen de fallback).
    resp = inst._execute_intent(_intent("time_query", {}), "que hora es")

    assert "hora" in resp
    assert len(sys_agent.calls) == 0


def test_sin_registry_no_rompe():
    inst = _make_stub()
    resp = inst._execute_intent(_intent("desconocida", {}), "frase")
    assert resp is not None
    assert "no tengo implementada" in resp


def test_agente_con_error_vuelve_a_fallback():
    inst = _make_stub()
    web = _FailingAgent("web_agent", {"crypto_price": True})
    registry = AgentRegistry()
    registry.register(web)
    inst.agent_registry = registry
    inst.decision_engine = _FakeDecisionEngine(AgentType.WEB)

    # El agente devuelve status "error" → fallback directo; crypto_price
    # no tiene acción directa, así que se responde "en desarrollo".
    resp = inst._execute_intent(_intent("crypto_price", {}), "cuanto vale bitcoin")

    assert "no tengo implementada" in resp
    assert len(web.calls) == 1


def test_agente_que_lanza_excepcion_vuelve_a_fallback():
    inst = _make_stub()
    web = _RaisingAgent("web_agent", {"crypto_price": True})
    registry = AgentRegistry()
    registry.register(web)
    inst.agent_registry = registry
    inst.decision_engine = _FakeDecisionEngine(AgentType.WEB)

    resp = inst._execute_intent(_intent("crypto_price", {}), "cuanto vale bitcoin")

    assert "no tengo implementada" in resp
    assert len(web.calls) == 1


# ────────── get_status ──────────

def test_get_status_incluye_agentes():
    inst = _make_stub()
    inst.state = JarvisState.IDLE
    inst.modules_ready = True
    inst.decision_context = types.SimpleNamespace(session_id="s1")
    inst._sr_available = False
    inst.memory = None
    inst.intent_recognizer = None
    inst.intent_processor = None
    inst.decision_engine = None
    inst.event_bus = None
    inst.error_handler = None
    inst.ws_server = None
    inst._load_name = lambda: "Jarvis"

    web = _FakeAgent("web_agent", {"weather_query": True, "crypto_price": True})
    registry = AgentRegistry()
    registry.register(web)
    inst.agent_registry = registry

    status = inst.get_status()

    assert len(status["agents"]) == 1
    info = status["agents"][0]
    assert info["type"] == "web_agent"
    assert info["active"] is True
    assert info["initialized"] is True
    assert info["capabilities"] == ["crypto_price", "weather_query"]
    assert status["modules"]["agents"] == 1
