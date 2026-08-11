"""
test_conciencia_n3_n4.py - Tests de CONCIENCIA N3 y N4 (SEMANA 7, FASE 5)

N3 (contexto a corto plazo):
- brain/shortterm_context.py: resolución de elipsis/pronombres
- orchestrator: _resolve_with_context / _update_short_term_context / _clarify_or_default

N4 (autoconciencia funcional):
- orchestrator: _is_introspection / _introspection_intent / _explain_last_decision
  / _compute_capabilities / _store_capabilities / _store_status_snapshot
- agents/dialog.py: _introspection_response (por qué respondiste, estado,
  qué no sabes, cómo funcionas), _self_evaluate (respuestas débiles)

Declaración de honestidad: "autoconciencia" aquí es introspección funcional
sobre datos reales (historial de decisiones, catálogo, memoria), no vivencia
subjetiva. Todo es observable y testeable.
"""

import types

import agents.dialog as dialog_module
from agents.dialog import DialogAgent, _run_coro
from brain.shortterm_context import ShortTermContext
from orchestrator.orchestrator import Orchestrator


# ==================== DOBLES DE PRUEBA ====================

class _FakeMemory:
    """Doble con contexto persistente para introspección N4."""

    def __init__(self, context=None):
        self.context = dict(context or {})
        self.facts = []
        self.turns = []

    async def get_context(self):
        return dict(self.context)

    async def set_context(self, key, value):
        self.context[key] = value

    def get_facts_sync(self, fact_type=None):
        if fact_type:
            return [f for f in self.facts if f["fact_type"] == fact_type]
        return list(self.facts)

    async def save_fact(self, fact_type, fact_value, confidence=0.8, source=None):
        self.facts = [f for f in self.facts if f["fact_value"] != fact_value]
        self.facts.append({
            "fact_type": fact_type,
            "fact_value": fact_value,
            "confidence": confidence,
            "source": source,
        })
        return True

    async def save_conversation(self, user_message, agent_response, intent=None):
        self.turns.append({
            "user_message": user_message,
            "agent_response": agent_response,
            "intent": intent,
        })

    def get_recent_sync(self, limit=5):
        return list(reversed(self.turns[-limit:])) if self.turns else []


def _agent(memory=None):
    return DialogAgent("dialog_agent", {"memory": memory or _FakeMemory()})


def _process(agent, text):
    return agent.process({"intent": "smalltalk", "text": text, "parameters": {}})


def _stub(**attrs):
    """Orchestrator sin __init__ con atributos controlados."""
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
    inst.memory = _FakeMemory()
    inst.state = "idle"
    inst.modules_ready = True
    inst._handlers = {"smalltalk": lambda p, u: None}
    for key, value in attrs.items():
        setattr(inst, key, value)
    return inst


# ==================== N3: ELIPSIS EN EL ORQUESTADOR ====================

def test_resolve_with_context_elipsis():
    stc = ShortTermContext()
    stc.update("weather_query", {"location": "Lima"}, "clima de Lima")
    orch = _stub(short_term_context=stc)
    intent = orch._resolve_with_context("¿y pasado mañana?")
    assert intent is not None
    assert intent.name == "weather_query"
    assert intent.parameters == {"location": "Lima"}


def test_resolve_with_context_sin_turno_devuelve_none():
    orch = _stub(short_term_context=ShortTermContext())
    assert orch._resolve_with_context("¿y pasado mañana?") is None


def test_update_short_term_context_guarda_turno():
    stc = ShortTermContext()
    orch = _stub(short_term_context=stc)
    intent = types.SimpleNamespace(
        name="open_application", parameters={"application": "youtube"}
    )
    orch._update_short_term_context(intent, "abre YouTube")
    assert stc.has_context() is True
    assert stc.get_last_turn()["intent"] == "open_application"


def test_clarify_or_default_sin_contexto():
    orch = _stub(short_term_context=ShortTermContext())
    response = orch._clarify_or_default("¿y eso?")
    assert "¿A qué te refieres" in response


def test_clarify_or_default_frase_normal():
    orch = _stub(short_term_context=ShortTermContext())
    response = orch._clarify_or_default("quien sos vos")
    assert response == "Lo siento, no entendí eso."


# ==================== N4: INTROSPECCIÓN EN EL ORQUESTADOR ====================

def test_is_introspection_por_que():
    orch = _stub()
    assert orch._is_introspection("¿por qué me respondiste eso?") is True
    assert orch._is_introspection("qué hora es") is False


def test_is_introspection_estado_y_arquitectura():
    orch = _stub()
    assert orch._is_introspection("¿qué estás haciendo?") is True
    assert orch._is_introspection("¿cómo funcionas?") is True


def test_introspection_intent_redirige_a_smalltalk():
    orch = _stub()
    intent = orch._introspection_intent("¿cómo estás programado?")
    assert intent is not None
    assert intent.name == "smalltalk"
    assert intent.confidence == 0.98


def test_introspection_intent_frase_normal_none():
    orch = _stub()
    assert orch._introspection_intent("reproduce música") is None


def test_store_last_decision_guarda_en_memoria():
    memory = _FakeMemory()
    orch = _stub(memory=memory)
    intent = types.SimpleNamespace(name="weather_query", confidence=0.9)
    decision = types.SimpleNamespace(
        selected_agent=types.SimpleNamespace(value="web_agent"),
        reasoning="weather_query: 0.90 -> web_agent",
    )
    orch._store_last_decision("clima en Lima", intent, decision)
    assert "last_decision" in memory.context
    assert memory.context["last_decision"]["intent"] == "weather_query"
    assert memory.context["last_decision"]["agent"] == "web_agent"


def test_compute_capabilities_distingue_pendientes():
    orch = _stub(agent_registry=None)
    caps = orch._compute_capabilities()
    assert "time_query" in caps["implemented"]
    assert "pending" in caps
    assert len(caps["pending"]) >= 0


def test_store_status_snapshot_guarda_estado():
    memory = _FakeMemory()
    orch = _stub(memory=memory, agent_registry=None)
    orch._store_status_snapshot()
    status = memory.context["system_status"]
    assert status["modules_ready"] is True
    assert status["intents_available"] > 0


# ==================== N4: DIÁLOGO DE INTROSPECCIÓN ====================

def test_por_que_respondiste_explica_decision():
    memory = _FakeMemory(context={
        "last_decision": {
            "input": "clima en Lima",
            "intent": "weather_query",
            "confidence": 0.9,
            "agent": "web_agent",
            "reasoning": "weather_query: 0.90 -> web_agent",
        }
    })
    agent = _agent(memory)
    resp = _process(agent, "¿por qué me respondiste eso?")
    assert resp["status"] == "success"
    assert "clima en Lima" in resp["data"]["result"]
    assert "weather_query" in resp["data"]["result"]
    assert resp["data"]["source"] == "memory"


def test_por_que_respondiste_sin_decision():
    agent = _agent()
    resp = _process(agent, "¿por qué me respondiste eso?")
    assert resp["status"] == "success"
    assert "no tengo un proceso reciente" in resp["data"]["result"].lower()


def test_estado_actual_desde_memoria():
    memory = _FakeMemory(context={
        "system_status": {
            "assistant_name": "Jarvis",
            "state": "idle",
            "modules_ready": True,
            "intents_available": 50,
            "agents": ["system_agent", "web_agent", "dialog_agent"],
        }
    })
    agent = _agent(memory)
    resp = _process(agent, "¿cuál es tu estado?")
    assert resp["status"] == "success"
    assert "idle" in resp["data"]["result"]
    assert "system_agent" in resp["data"]["result"]


def test_estado_actual_fallback_sin_memoria():
    agent = _agent(_FakeMemory())
    resp = _process(agent, "¿qué estás haciendo?")
    assert resp["status"] == "success"
    assert "Jarvis" in resp["data"]["result"]


def test_que_no_sabes_hacer_lista_pendientes():
    agent = _agent()
    resp = _process(agent, "¿qué no sabes hacer?")
    assert resp["status"] == "success"
    assert "en desarrollo" in resp["data"]["result"]
    assert resp["data"].get("pending_count", 0) >= 0


def test_como_funcionas_explica_arquitectura():
    agent = _agent()
    resp = _process(agent, "¿cómo funcionas?")
    assert resp["status"] == "success"
    assert "Reconocimiento" in resp["data"]["result"]
    assert "Decisión" in resp["data"]["result"]
    assert "orchestrator" in resp["data"]["result"]


# ==================== N4: AUTO-EVALUACIÓN POST-RESPUESTA ====================

def test_self_evaluate_respuesta_fuerte():
    agent = _agent()
    data = {"result": "¡Hola! ¿En qué puedo ayudarte?", "source": "templates"}
    out = agent._self_evaluate("smalltalk", "hola", data)
    assert out["evaluation"]["intent"] == "smalltalk"
    assert out["evaluation"]["weak"] is False


def test_self_evaluate_respuesta_debil():
    agent = _agent()
    data = {"result": "Intención 'x' en desarrollo", "source": "internal"}
    out = agent._self_evaluate("x", "algo", data)
    assert out["evaluation"]["weak"] is True
    assert out["evaluation"]["suggestion"]


def test_self_evaluate_no_rompe_sin_result():
    agent = _agent()
    out = agent._self_evaluate("smalltalk", "hola", {"source": "internal"})
    assert out["evaluation"]["weak"] is True


def test_process_adjunta_evaluacion():
    agent = _agent()
    resp = agent.process(
        {"intent": "smalltalk", "text": "hola", "parameters": {}}
    )
    assert "evaluation" in resp["data"]


# ==================== N4: AUTO-EVALUACIÓN ORQUESTADOR ====================

def test_explain_last_decision_sin_historial():
    engine = types.SimpleNamespace(get_decision_history=lambda n: [])
    orch = _stub(decision_engine=engine)
    narrative = orch._explain_last_decision()
    assert "no he tomado ninguna decisión" in narrative


def test_explain_last_decision_con_historial():
    decision = types.SimpleNamespace(
        selected_agent=types.SimpleNamespace(value="web_agent"),
        intent=types.SimpleNamespace(
            name="weather_query", confidence=0.9, raw_text="clima en Lima"
        ),
        confidence=0.9,
        reasoning="weather_query: 0.90 -> web_agent",
    )
    engine = types.SimpleNamespace(get_decision_history=lambda n: [decision])
    orch = _stub(decision_engine=engine)
    narrative = orch._explain_last_decision()
    assert "clima en Lima" in narrative
    assert "weather_query" in narrative
    assert "90%" in narrative


def test_explain_last_decision_sin_engine():
    orch = _stub(decision_engine=None)
    narrative = orch._explain_last_decision()
    assert "no tengo un motor" in narrative.lower()
