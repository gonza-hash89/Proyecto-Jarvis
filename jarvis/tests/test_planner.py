"""
test_planner.py - SEMANA 8, FASE 1: TaskPlanner multi-paso

Cubre:
1. Unitarios del TaskPlanner puro (decompose/execute/report/failure).
2. Integración con el orquestador (stub sin __init__) + agentes reales
   (FileAgent con SQLite temporal) para metas como "organiza mi semana".
3. Degradación elegante: fallo del agente de datos -> plan alternativo.
"""

import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.registry import AgentRegistry
from brain.planner import TaskPlanner, _normalize, _PLAN_TRIGGERS
from orchestrator.orchestrator import JarvisState, Orchestrator


# ==================== DOBLES DE PRUEBA ====================

class _FakeMemory:
    """Memoria con el contrato async del MemoryManager real."""

    def __init__(self):
        self.context = {}

    async def get_context(self):
        return self.context

    async def set_context(self, context_key, context_value):
        self.context[context_key] = context_value


def _make_stub(memory=None):
    """Instancia de Orchestrator sin __init__ (evita voz/memoria/red)."""
    inst = object.__new__(Orchestrator)
    # data_dir temporal: evita tocar el data/ real y bloqueos de SQLite.
    inst._tmpdir = tempfile.mkdtemp(prefix="jarvis_planner_test_")
    inst.config = types.SimpleNamespace(
        base_dir=".",
        data_dir=inst._tmpdir,
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
    inst.set_state = lambda state: setattr(inst, "state", state)
    inst._plan_step_results = {}
    inst._plan_pending = None
    inst._current_goal_text = ""
    return inst


def _file_agent_with_tasks(db_path, tasks):
    """Crea un FileAgent conectado a SQLite temporal con tareas."""
    from agents.file import FileAgent

    agent = FileAgent("file_agent", {"db_path": db_path})
    for task in tasks:
        agent.process({
            "intent": "create_task",
            "parameters": {"task_description": task},
            "text": f"agrega la tarea {task}",
        })
    return agent


def _stub_with_planner(tasks=None):
    """Stub del orquestador con planner + FileAgent (SQLite temporal)."""
    inst = _make_stub()
    inst.agent_registry = AgentRegistry()
    if tasks is not None:
        db_path = os.path.join(inst._tmpdir, "jarvis_memory.db")
        agent = _file_agent_with_tasks(db_path, tasks)
        inst.agent_registry.register(agent)
    inst.planner = TaskPlanner(
        executor=inst._execute_planner_step, logger=inst.logger
    )
    return inst


# ==================== UNITARIOS DEL PLANNER ====================

def test_normalize_quita_tildes_y_minusculas():
    assert _normalize("Organiza MI semana") == "organiza mi semana"
    assert _normalize("¿qué tengo pendiente?") == "que tengo pendiente"


def test_decompose_organizar():
    planner = TaskPlanner()
    plan = planner.decompose("organiza mi semana")
    intents = [s["intent"] for s in plan]
    assert intents == ["list_tasks", "prioritize", "summary"]
    assert all(s["agent"] for s in plan)


def test_decompose_variantes_organizar():
    planner = TaskPlanner()
    assert len(planner.decompose("organiza mis tareas de hoy")) == 3
    assert len(planner.decompose("planifica mi día")) == 3
    assert len(planner.decompose("organize my week")) == 3


def test_decompose_pendientes():
    planner = TaskPlanner()
    plan = planner.decompose("que tengo pendiente esta semana")
    intents = [s["intent"] for s in plan]
    assert intents == ["list_tasks", "calendar_event", "summary"]


def test_decompose_sin_plan():
    planner = TaskPlanner()
    assert planner.decompose("qué hora es") == []


def test_triggers_cubren_variantes_requeridas():
    org = _PLAN_TRIGGERS["organizar"]
    pend = _PLAN_TRIGGERS["pendientes"]
    assert "organiza mi semana" in org
    assert "organiza mis tareas de hoy" in org
    assert "que tengo pendiente esta semana" in pend


def test_execute_plan_ok():
    fake = lambda step: {"result": step["intent"] + " ok", "status": "success"}
    planner = TaskPlanner(executor=fake)
    plan = planner.decompose("organiza mi semana")
    result = planner.execute_plan(plan)
    assert result["status"] == "completed"
    assert len(result["results"]) == 3
    assert "3/3" in result["report"]


def test_execute_plan_recupera_con_alternativa():
    def fake(step):
        if step["intent"] == "list_tasks":
            return {"result": "boom", "status": "error"}
        return {"result": "ok", "status": "success"}

    planner = TaskPlanner(executor=fake)
    plan = planner.decompose("organiza mis tareas")
    result = planner.execute_plan(plan)
    # list_tasks falla pero su alternativa (recent_conversations) funciona.
    assert result["status"] == "completed"
    assert result["report"].count("[ok]") == 3


def test_execute_plan_falla_sin_recuperacion():
    hard = lambda step: {"result": "boom", "status": "error"}
    planner = TaskPlanner(executor=hard)
    plan = planner.decompose("organiza mi semana")
    result = planner.execute_plan(plan)
    assert result["status"] == "failed"
    assert "[x]" in result["report"]


def test_execute_plan_sin_executor():
    planner = TaskPlanner()
    plan = planner.decompose("organiza mi semana")
    result = planner.execute_plan(plan)
    assert result["status"] == "no_executor"


def test_execute_plan_vacio():
    planner = TaskPlanner()
    result = planner.execute_plan([])
    assert result["status"] == "empty"


def test_handle_failure_reglas():
    planner = TaskPlanner()
    alt = planner.handle_failure({"id": 1, "agent": "file_agent", "intent": "list_tasks"})
    assert alt is not None
    assert alt["intent"] == "recent_conversations"
    assert planner.handle_failure({"id": 3, "agent": "planner", "intent": "summary"}) is None


def test_reset_limpia_estado():
    fake = lambda step: {"result": "ok", "status": "success"}
    planner = TaskPlanner(executor=fake)
    planner.execute_plan(planner.decompose("organiza mi semana"))
    assert planner.get_log()
    planner.reset()
    assert planner.get_log() == []
    assert planner.report_progress() == "No hay plan en curso."


# ==================== INTEGRACIÓN CON EL ORQUESTADOR ====================

def test_maybe_run_plan_no_es_meta():
    inst = _stub_with_planner()
    assert inst._maybe_run_plan("qué hora es") is None


def test_maybe_run_plan_sin_planner():
    inst = _make_stub()
    inst.planner = None
    assert inst._maybe_run_plan("organiza mi semana") is None


def test_organizar_tareas_con_file_agent():
    inst = _stub_with_planner(tasks=["comprar pan", "pagar impuestos"])
    response = inst._maybe_run_plan("organiza mis tareas de hoy")
    assert response is not None
    assert "2 tareas pendientes" in response
    assert "comprar pan" in response
    assert "pagar impuestos" in response


def test_organizar_sin_tareas():
    inst = _stub_with_planner(tasks=[])
    response = inst._maybe_run_plan("organiza mi semana")
    assert response is not None
    assert "No tienes tareas pendientes" in response


def test_process_input_delega_plan():
    inst = _stub_with_planner(tasks=["comprar pan"])
    response = inst.process_input("organiza mi semana")
    assert response is not None
    assert "1 tarea pendiente" in response


def test_plan_falla_sin_agente_de_datos():
    # Sin FileAgent registrado: list_tasks falla y se usa la alternativa
    # (recent_conversations). El plan no puede priorizar pero termina.
    inst = _stub_with_planner()  # agent_registry vacío
    response = inst._maybe_run_plan("organiza mi semana")
    assert response is not None
    assert response != ""


def test_plan_reporta_progreso_y_eventos():
    events = []

    def capture(*a, **k):
        events.append(a[0] if a else k)

    inst = _make_stub()
    inst._publish = capture
    inst.agent_registry = AgentRegistry()
    inst.planner = TaskPlanner(executor=inst._execute_planner_step, logger=inst.logger)
    inst._maybe_run_plan("organiza mi semana")
    names = [e if isinstance(e, str) else getattr(e, "value", str(e)) for e in events]
    assert "plan_started" in names
    assert "plan_step_completed" in names
    assert "plan_finished" in names
