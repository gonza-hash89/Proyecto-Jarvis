"""
test_orchestrator_connectivity.py - CONCIENCIA N4: introspección y auto-evaluación

Verifica la conectividad de la autoconciencia funcional de Jarvis:

Orquestador → memoria (exposición del estado real):
- _store_last_decision(): guarda la última decisión en contexto.
- _store_status_snapshot(): guarda un snapshot del sistema.
- _store_capabilities(): guarda intenciones implementadas vs. pendientes.

DialogAgent → memoria (lectura para responder):
- Preguntas de introspección (por qué respondiste, estado, límites, arquitectura).
- Auto-evaluación post-respuesta: marca respuestas débiles sin alterarlas.
"""

import types
from typing import Any, Dict

from agents.dialog import (
    _INTROSPECTION_ARCH,
    _INTROSPECTION_STATUS,
    _INTROSPECTION_UNKNOWN,
    _INTROSPECTION_WHY,
    _WEAK_MARKERS,
    DialogAgent,
)
from brain.intent_data import INTENT_CATALOG
from orchestrator.orchestrator import JarvisState, Orchestrator


# ==================== DOBLES DE PRUEBA ====================

class _FakeMemory:
    """Memoria corto plazo con el contrato async del MemoryManager real."""

    def __init__(self):
        self.context: Dict[str, Any] = {}

    async def get_context(self) -> Dict[str, Any]:
        return self.context

    async def set_context(self, context_key: str, context_value: Any):
        self.context[context_key] = context_value


def _make_stub(memory=None):
    """Instancia de Orchestrator sin __init__ (evita voz/memoria/red)."""
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
        error=lambda *a, **k: None,
    )
    inst.engine = None
    inst._voice_available = False
    inst.is_running = True
    inst.state = JarvisState.IDLE
    inst.modules_ready = True
    inst.memory = memory if memory is not None else _FakeMemory()
    inst._run_async = Orchestrator._run_async
    inst._load_name = lambda: "Jarvis"
    return inst


def _dialog(memory=None):
    config = {}
    if memory is not None:
        config["memory"] = memory
    return DialogAgent("dialog_agent", config)


def _intent(name="time_query", confidence=0.98):
    return types.SimpleNamespace(name=name, confidence=confidence)


def _decision(agent="system_agent", reasoning="Acción directa de alta confianza"):
    return types.SimpleNamespace(
        selected_agent=types.SimpleNamespace(value=agent),
        reasoning=reasoning,
    )


# ── Carga de la introspección (módulo) ──

def test_n4_carga_introspeccion():
    assert _INTROSPECTION_WHY and _INTROSPECTION_STATUS
    assert _INTROSPECTION_UNKNOWN and _INTROSPECTION_ARCH
    assert len(_WEAK_MARKERS) >= 1


# ── Orquestador → memoria (exposición del estado real) ──

def test_n4_last_decision_almacena():
    memory = _FakeMemory()
    inst = _make_stub(memory)
    inst._store_last_decision("¿qué hora es?", _intent(), _decision())

    stored = memory.context.get("last_decision")
    assert stored is not None
    assert stored["intent"] == "time_query"
    assert stored["confidence"] == 0.98
    assert stored["agent"] == "system_agent"
    assert stored["input"] == "¿qué hora es?"


def test_n4_estado_introspeccion():
    memory = _FakeMemory()
    inst = _make_stub(memory)
    inst._store_status_snapshot()

    status = memory.context.get("system_status")
    assert status is not None
    assert status["assistant_name"] == "Jarvis"
    assert status["modules_ready"] is True
    assert status["intents_available"] == len(INTENT_CATALOG)
    assert "state" in status


def test_n4_capacidades_introspeccion():
    memory = _FakeMemory()
    inst = _make_stub(memory)
    inst._store_capabilities()

    caps = memory.context.get("capabilities")
    assert caps is not None
    assert isinstance(caps["pending"], list)
    assert len(caps["pending"]) >= 1
    assert all(name in INTENT_CATALOG for name in caps["pending"])


# ── DialogAgent: preguntas de introspección (N4) ──

def test_n4_smalltalk_por_que_me_respondiste():
    agent = _dialog()
    resp = agent.process({"intent": "smalltalk", "text": "¿por qué me respondiste eso?"})
    assert resp["status"] == "success"
    assert "Todavía no tengo un proceso reciente" in resp["data"]["result"]


def test_n4_smalltalk_cual_es_tu_estado():
    agent = _dialog()
    resp = agent.process({"intent": "smalltalk", "text": "¿cuál es tu estado?"})
    assert resp["status"] == "success"
    assert "Motor de conversación" in resp["data"]["result"]


def test_n4_smalltalk_que_no_sabes_hacer():
    agent = _dialog()
    resp = agent.process({"intent": "smalltalk", "text": "¿qué no sabes hacer?"})
    assert resp["status"] == "success"
    assert "en desarrollo" in resp["data"]["result"]


def test_n4_smalltalk_como_funcionas():
    agent = _dialog()
    resp = agent.process({"intent": "smalltalk", "text": "¿cómo funcionas?"})
    assert resp["status"] == "success"
    assert "capas" in resp["data"]["result"] or "arquitectura" in resp["data"]["result"]


def test_n4_pending_count():
    agent = _dialog()
    resp = agent.process({"intent": "smalltalk", "text": "¿qué no sabes hacer?"})
    assert resp["data"]["pending_count"] == len(resp["data"]["pending"])
    assert resp["data"]["pending_count"] >= 1


# ── Conectividad: orquestador escribe → dialog lee ──

def test_n4_smalltalk_lee_estado_real_de_memoria():
    memory = _FakeMemory()
    inst = _make_stub(memory)
    inst._store_status_snapshot()
    inst._store_capabilities()

    agent = _dialog(memory)
    resp = agent.process({"intent": "smalltalk", "text": "¿cuál es tu estado?"})

    assert resp["status"] == "success"
    assert resp["data"]["source"] == "memory"
    assert "Jarvis" in resp["data"]["result"]


def test_n4_smalltalk_explica_ultima_decision():
    memory = _FakeMemory()
    inst = _make_stub(memory)
    inst._store_last_decision(
        "¿qué hora es?",
        _intent("time_query", 0.98),
        _decision("system_agent", "Acción directa de alta confianza"),
    )

    agent = _dialog(memory)
    resp = agent.process({"intent": "smalltalk", "text": "¿por qué me respondiste eso?"})

    assert resp["status"] == "success"
    assert resp["data"]["source"] == "memory"
    assert "time_query" in resp["data"]["result"]
    assert "98%" in resp["data"]["result"]
    assert "system_agent" in resp["data"]["result"]


# ── Auto-evaluación post-respuesta (N4) ──

def test_n4_self_eval_debil():
    agent = _dialog()
    resp = agent.process({"intent": "hack_the_pentagon", "text": "hackea el pentágono"})
    assert resp["status"] == "success"
    assert resp["data"]["evaluation"]["weak"] is True
    assert resp["data"]["evaluation"]["intent"] == "hack_the_pentagon"


def test_n4_self_eval_fuerte():
    agent = _dialog()
    resp = agent.process({"intent": "smalltalk", "text": "hola"})
    assert resp["status"] == "success"
    assert resp["data"]["evaluation"]["weak"] is False
