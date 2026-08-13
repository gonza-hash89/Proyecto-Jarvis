"""
test_agent_coordinator.py - SEMANA 8, FASE 3: coordinación de agentes

Cubre el AgentCoordinator: derivación de eventos de dominio desde el bus
(action_completed -> weather_data_ready / task_completed), pipelines
multi-agente con timeout y encadenamiento asíncrono ("on_<intent>").
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.agent_coordinator import AgentCoordinator


# ==================== DOBLES DE PRUEBA ====================

class _FakeEvent:
    def __init__(self, name, payload=None):
        self.name = name
        self.payload = payload or {}


class _FakeBus:
    def __init__(self):
        self.published = []
        self.subscribers = {}

    def subscribe(self, event_name, callback):
        self.subscribers.setdefault(event_name, []).append(callback)

    def publish(self, event, priority=None):
        self.published.append(event)


class _FakeMemory:
    def __init__(self):
        self.context = {}

    async def set_context(self, key, value):
        self.context[key] = value

    async def get_context(self):
        return self.context


class _FakeAgent:
    def __init__(self, result=None, delay=0.0):
        self.result = result or {"status": "success", "data": {"result": "ok"}}
        self.delay = delay
        self.messages = []
        self.agent_type = "fake_agent"

    def process(self, message):
        self.messages.append(message)
        if self.delay:
            time.sleep(self.delay)
        return self.result


class _FakeRegistry:
    def __init__(self, agents):
        self._agents = {a.agent_type: a for a in agents}

    def get(self, agent_type):
        return self._agents.get(agent_type)


def _logger():
    import types

    return types.SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )


def _coord(bus=None, memory=None, registry=None, timeout=10.0):
    return AgentCoordinator(
        registry=registry,
        event_bus=bus,
        memory=memory if memory is not None else _FakeMemory(),
        logger=_logger(),
        default_timeout=timeout,
    )


# ==================== PIPELINES ====================

def test_run_pipeline_completa():
    agent = _FakeAgent(result={"status": "success", "data": {"result": "soleado"}})
    coord = _coord(registry=_FakeRegistry([agent]))
    coord.register_pipeline("clima", [
        {"agent": "fake_agent", "intent": "weather_query", "params": {"location": "Lima"}},
    ])
    result = coord.run_pipeline("clima")
    assert result["status"] == "completed"
    assert len(result["results"]) == 1
    step_out = result["results"][1]
    assert step_out["data"]["result"] == "soleado"
    assert agent.messages[0]["intent"] == "weather_query"


def test_run_pipeline_datos_fluidos_al_siguiente_paso():
    """El resultado del paso queda en ctx para el siguiente (ctx[intent])."""
    web = _FakeAgent(result={"status": "success", "data": {"result": "Lima 18°C"}})
    coord = _coord(registry=_FakeRegistry([web]), memory=None)
    captured = {}

    def spy(step, ctx):
        captured["ctx"] = ctx
        return {"status": "success", "data": {"result": "guardado"}}

    coord.register_pipeline("p", [
        {"agent": "fake_agent", "intent": "weather_query", "params": {}},
        {"agent": "memory", "operation": "noop"},
    ])
    # Reemplazamos el paso de memoria con un espía para inspeccionar el ctx.
    # Los pasos de agentes siguen usando la lógica original.
    original = coord._run_step

    def spy(step, ctx):
        if step["agent"] != "memory":
            return original(step, ctx)
        captured["ctx"] = dict(ctx)
        return {"status": "success", "data": {"result": "guardado"}}

    coord._run_step = spy
    result = coord.run_pipeline("p")
    assert result["status"] == "completed"
    assert captured["ctx"]["weather_query"]["result"] == "Lima 18°C"


def test_run_pipeline_no_registrada():
    coord = _coord()
    result = coord.run_pipeline("nope")
    assert result["status"] == "missing"


def test_run_pipeline_vacia_no_registra():
    coord = _coord()
    coord.register_pipeline("vacia", [])
    assert "vacia" not in coord._pipelines


def test_run_pipeline_falla_agente_ausente():
    coord = _coord(registry=_FakeRegistry([]))
    coord.register_pipeline("x", [
        {"agent": "fantasma", "intent": "noop", "params": {}},
    ])
    result = coord.run_pipeline("x")
    assert result["status"] == "failed"
    step = result["results"][1]
    assert step["status"] == "error"


def test_run_pipeline_timeout():
    slow = _FakeAgent(delay=1.5)
    coord = _coord(registry=_FakeRegistry([slow]), timeout=0.3)
    coord.register_pipeline("lenta", [
        {"agent": "fake_agent", "intent": "weather_query", "params": {}},
        {"agent": "fake_agent", "intent": "news_query", "params": {}},
    ])
    result = coord.run_pipeline("lenta")
    assert result["status"] == "timeout"


def test_memory_step_set_context():
    memory = _FakeMemory()
    coord = _coord(memory=memory)
    coord.register_pipeline("mem", [
        {"agent": "memory", "operation": "set_context",
         "params": {"key": "clave", "value": "valor"}},
    ])
    result = coord.run_pipeline("mem")
    assert result["status"] == "completed"
    assert memory.context["clave"] == "valor"


def test_get_task_y_get_status():
    agent = _FakeAgent()
    coord = _coord(registry=_FakeRegistry([agent]))
    coord.register_pipeline("ok", [
        {"agent": "fake_agent", "intent": "noop", "params": {}},
    ])
    result = coord.run_pipeline("ok")
    task = coord.get_task(result["task_id"])
    assert task["status"] == "completed"
    status = coord.get_status()
    assert "ok" in status["pipelines"]
    assert status["tasks"] == 1


# ==================== EVENTOS DE DOMINIO ====================

def test_action_completed_deriva_weather():
    bus = _FakeBus()
    memory = _FakeMemory()
    coord = _coord(bus=bus, memory=memory)
    coord.subscribe_events()
    coord.handle_event(_FakeEvent("action_completed", {
        "intent": "weather_query", "result": "Lima 18°C",
    }))
    names = [e.name for e in bus.published]
    assert "weather_data_ready" in names
    assert coord.get_last_derived("weather_data_ready")["intent"] == "weather_query"
    assert "event::weather_data_ready" in memory.context


def test_action_completed_deriva_task():
    bus = _FakeBus()
    coord = _coord(bus=bus)
    coord.handle_event(_FakeEvent("action_completed", {
        "intent": "create_task", "result": "Tarea agregada",
    }))
    names = [e.name for e in bus.published]
    assert "task_completed" in names


def test_action_completed_sin_derivacion():
    bus = _FakeBus()
    coord = _coord(bus=bus)
    coord.handle_event(_FakeEvent("action_completed", {
        "intent": "play_music", "result": "Reproduciendo",
    }))
    assert bus.published == []


def test_action_failed_no_deriva():
    bus = _FakeBus()
    coord = _coord(bus=bus)
    coord.handle_event(_FakeEvent("action_failed", {
        "intent": "weather_query", "error": "boom",
    }))
    assert bus.published == []


def test_subscribe_events_idempotente():
    bus = _FakeBus()
    coord = _coord(bus=bus)
    coord.subscribe_events()
    coord.subscribe_events()
    assert len(bus.subscribers.get("action_completed", [])) == 1


def test_follow_up_pipeline_se_encadena():
    """Al derivar weather_data_ready se dispara la pipeline on_weather_query."""
    bus = _FakeBus()
    memory = _FakeMemory()
    coord = _coord(bus=bus, memory=memory)
    coord.register_pipeline("on_weather_query", [
        {"agent": "memory", "operation": "set_context",
         "params": {"key": "event_weather_logged", "value": "clima consultado"}},
    ])
    coord.handle_event(_FakeEvent("action_completed", {
        "intent": "weather_query", "result": "Lima 18°C",
    }))
    time.sleep(0.4)
    assert memory.context.get("event_weather_logged") == "clima consultado"


def test_run_pipeline_async_usa_hilo():
    agent = _FakeAgent(delay=0.3)
    coord = _coord(registry=_FakeRegistry([agent]), timeout=5.0)
    done = []
    coord.register_pipeline("async_test", [
        {"agent": "fake_agent", "intent": "noop", "params": {}},
    ])
    coord.run_pipeline_async("async_test", on_done=lambda r: done.append(r["status"]))
    assert done == []  # aún corriendo
    time.sleep(0.8)
    assert done == ["completed"]
