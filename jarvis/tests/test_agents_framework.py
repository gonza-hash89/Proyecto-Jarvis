"""
Tests de agents/base.py, agents/registry.py y agents/factory.py (SEMANA 5, FASE 0)

Cubre la infraestructura compartida:
- AgentBase: ciclo de vida, logging, errores y _safe_call
- AgentRegistry: registro, búsqueda, ciclo de vida en lote
- AgentFactory: creación con degradación elegante
"""

import agents.factory as factory_mod
from agents.base import AgentBase
from agents.factory import AgentFactory
from agents.registry import AgentRegistry
from brain.decision import AgentType


# ────────── Helper: agente concreto mínimo ──────────

class _DummyAgent(AgentBase):
    def process(self, message):
        return {"status": "success", "data": message}

    def handle_event(self, event):
        pass


def _dummy(agent_type="dummy"):
    return _DummyAgent(name=agent_type, agent_type=agent_type)


# ────────── AgentBase ──────────

def test_hereda_y_estado_inicial():
    agent = _dummy()
    assert isinstance(agent, AgentBase)
    assert agent.initialized is False
    assert agent.is_active is True
    assert agent.has_errors() is False


def test_initialize_y_cleanup():
    agent = _dummy()
    assert agent.initialize() is True
    assert agent.initialized is True
    agent.cleanup()
    assert agent.initialized is False


def test_stop_detiene_y_limpia():
    agent = _dummy()
    agent.initialize()
    assert agent.initialized is True
    agent.stop()
    assert agent.is_active is False
    assert agent.initialized is False


def test_stop_con_cleanup_fallido(monkeypatch):
    agent = _dummy()

    def cleanup_roto():
        raise RuntimeError("no se pudo limpiar")

    monkeypatch.setattr(agent, "cleanup", cleanup_roto)
    agent.stop()
    assert agent.is_active is False
    assert agent.has_errors() is True


def test_get_info():
    agent = _dummy()
    agent.initialize()
    info = agent.get_info()
    assert info["name"] == "dummy"
    assert info["type"] == "dummy"
    assert info["initialized"] is True
    assert info["errors"] == 0


def test_errores_registro_y_limpieza():
    agent = _dummy()
    agent.record_error("op1", ValueError("uno"))
    agent.record_error("op2", KeyError("dos"))
    assert agent.has_errors() is True
    assert len(agent.get_errors()) == 2
    assert "op1" in agent.get_errors()[0]
    agent.clear_errors()
    assert agent.has_errors() is False


def test_safe_call_ok():
    agent = _dummy()
    result = agent._safe_call("suma", lambda a, b: a + b, 2, 3)
    assert result == 5
    assert agent.has_errors() is False


def test_safe_call_error():
    agent = _dummy()
    result = agent._safe_call("div", lambda: 1 / 0)
    assert result is None
    assert agent.has_errors() is True


# ────────── AgentRegistry ──────────

def test_register_none_es_falso():
    registry = AgentRegistry()
    assert registry.register(None) is False
    assert registry.get_count() == 0


def test_register_y_get():
    registry = AgentRegistry()
    agent = _dummy("sys")
    assert registry.register(agent) is True
    assert registry.get("sys") is agent


def test_register_duplicado_reemplaza():
    registry = AgentRegistry()
    first = _dummy("sys")
    second = _dummy("sys")
    assert registry.register(first) is True
    assert registry.register(second) is True
    assert registry.get_count() == 1
    assert registry.get("sys") is second


def test_get_desconocido_devuelve_none():
    registry = AgentRegistry()
    assert registry.get("fantasma") is None


def test_list_solo_activos():
    registry = AgentRegistry()
    a = _dummy("a")
    b = _dummy("b")
    registry.register(a)
    registry.register(b)
    assert len(registry.list()) == 2
    a.stop()
    assert registry.list() == [b]


def test_list_all():
    registry = AgentRegistry()
    a = _dummy("a")
    registry.register(a)
    a.stop()
    assert registry.list_all() == [a]


def test_start_all_y_resultados():
    registry = AgentRegistry()
    registry.register(_dummy("a"))
    results = registry.start_all()
    assert results == {"a": True}
    assert registry.get("a").initialized is True


def test_start_all_con_error():
    registry = AgentRegistry()

    class _Roto(AgentBase):
        def initialize(self):
            raise RuntimeError("boom")

        def process(self, message):
            return {"status": "success", "data": message}

        def handle_event(self, event):
            pass

    registry.register(_Roto(name="a", agent_type="a"))
    results = registry.start_all()
    assert results["a"] is False
    assert registry.get("a").has_errors() is True


def test_stop_all():
    registry = AgentRegistry()
    a = _dummy("a")
    b = _dummy("b")
    registry.register(a)
    registry.register(b)
    registry.start_all()
    registry.stop_all()
    assert a.is_active is False
    assert b.is_active is False


def test_clear_y_count():
    registry = AgentRegistry()
    registry.register(_dummy("a"))
    registry.register(_dummy("b"))
    assert registry.get_count() == 2
    registry.clear()
    assert registry.get_count() == 0


# ────────── AgentFactory ──────────

def test_create_system_agent():
    agent = AgentFactory().create(AgentType.SYSTEM)
    assert agent is not None
    assert agent.agent_type == "system_agent"


def test_create_con_string():
    agent = AgentFactory().create("web_agent")
    assert agent is not None
    assert agent.agent_type == "web_agent"


def test_create_string_desconocida():
    assert AgentFactory().create("tipo_inexistente") is None


def test_create_no_soportado():
    assert AgentFactory().create(AgentType.VOICE) is None
    assert AgentFactory().create(AgentType.MEMORY) is None


def test_create_fusiona_config():
    agent = AgentFactory(config={"base": 1}).create(AgentType.SYSTEM, {"extra": 2})
    assert agent.config["base"] == 1
    assert agent.config["extra"] == 2


def test_create_import_error(monkeypatch):
    def boom(name):
        raise ImportError(f"no existe {name}")

    monkeypatch.setattr(factory_mod.importlib, "import_module", boom)
    assert AgentFactory().create(AgentType.SYSTEM) is None


def test_create_constructor_error(monkeypatch):
    class _Malo:
        def __init__(self, *args, **kwargs):
            raise ValueError("constructor falló")

    class _ModuloFake:
        SystemAgent = _Malo

    monkeypatch.setattr(
        factory_mod.importlib, "import_module", lambda name: _ModuloFake()
    )
    assert AgentFactory().create(AgentType.SYSTEM) is None


def test_supported_types():
    tipos = AgentFactory().supported_types()
    assert AgentType.SYSTEM in tipos
    assert AgentType.WEB in tipos
    assert AgentType.DIALOG in tipos
    assert len(tipos) == 3
