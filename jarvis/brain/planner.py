"""
brain/planner.py - Planificador multi-paso (SEMANA 8, FASE 1)

Convierte metas de alto nivel ("organiza mi semana") en una secuencia de
sub-tareas que se ejecutan en orden lógico, reportando avance en cada paso
y con un plan alternativo si algo falla.

DECLARACION DE HONESTIDAD:
Esto NO es razonamiento automático general. Son plantillas de planes
(goals -> pasos concretos) con un ejecutor inyectable. Todo es
determinista, observable y testeable.
"""

import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


_NORM = {
    "á": "a", "à": "a", "â": "a", "ä": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o", "ö": "o",
    "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "ñ": "n", "ç": "c", "¿": "", "?": "", "¡": "", "!": "",
}

# Frases que disparan cada plan (normalizadas).
_PLAN_TRIGGERS: Dict[str, List[str]] = {
    "organizar": [
        "organiza mi semana", "organizame la semana", "organiza mis tareas",
        "organiza mis pendientes", "organiza mi dia", "organiza mis tareas de hoy",
        "planifica mi dia", "planifica mi semana", "plan mi semana",
        "organize my week", "plan my day",
    ],
    "pendientes": [
        "que tengo pendiente esta semana", "que tengo pendiente hoy",
        "que hay pendiente esta semana", "que tengo que hacer esta semana",
        "cuales son mis pendientes", "que tengo agendado",
        "what do i have pending this week", "what is on my schedule",
    ],
}


def _normalize(text: str) -> str:
    """Normaliza texto para comparación de planes."""
    norm = (text or "").lower()
    for k, v in _NORM.items():
        norm = norm.replace(k, v)
    return re.sub(r"\s+", " ", norm).strip()


# Pasos de cada plan. Cada paso: agent, intent, params, description.
# El ejecutor se encarga de resolver cómo se atiende ese intent.
_ORGANIZAR_STEPS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "agent": "file_agent",
        "intent": "list_tasks",
        "params": {},
        "description": "Leer tus tareas pendientes",
    },
    {
        "id": 2,
        "agent": "planner",
        "intent": "prioritize",
        "params": {},
        "description": "Priorizar tus tareas",
    },
    {
        "id": 3,
        "agent": "planner",
        "intent": "summary",
        "params": {},
        "description": "Armar el plan del día",
    },
]

_PENDIENTES_STEPS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "agent": "file_agent",
        "intent": "list_tasks",
        "params": {},
        "description": "Revisar tus tareas abiertas",
    },
    {
        "id": 2,
        "agent": "calendar_agent",
        "intent": "calendar_event",
        "params": {},
        "description": "Consultar tus eventos de la semana",
    },
    {
        "id": 3,
        "agent": "planner",
        "intent": "summary",
        "params": {},
        "description": "Cruzar tareas y eventos",
    },
]


class TaskPlanner:
    """Planificador multi-paso con ejecutor inyectable.

    El executor es un callable que recibe un paso (dict) y devuelve un
    dict con al menos {"result": str} (y opcionalmente "status"). Si el
    executor no se provee, los pasos se registran sin ejecutar (modo
    análisis: útil para probar decompose()).
    """

    def __init__(
        self,
        executor: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        logger: Optional[Any] = None,
    ) -> None:
        self._executor = executor
        self._logger = logger
        self._current_plan: List[Dict[str, Any]] = []
        self._current_goal: str = ""
        self._results: Dict[int, Dict[str, Any]] = {}
        self._status: Dict[int, str] = {}
        self._started_at: Optional[str] = None
        self._finished_at: Optional[str] = None
        self._log: List[str] = []

    # ==================== DESCOMPOSICIÓN ====================

    def decompose(self, goal: str) -> List[Dict[str, Any]]:
        """Descompone una meta en subtareas ordenadas.

        Returns:
            Lista de pasos (dicts), o [] si la meta no tiene plan.
        """
        norm = _normalize(goal)
        for plan_key in _PLAN_TRIGGERS:
            if any(trigger in norm for trigger in _PLAN_TRIGGERS[plan_key]):
                self._current_goal = goal
                self._current_plan = (
                    _ORGANIZAR_STEPS if plan_key == "organizar" else _PENDIENTES_STEPS
                )
                self._log.append(
                    f"Plan detectado '{plan_key}' para: {goal} ({len(self._current_plan)} pasos)"
                )
                return [dict(step) for step in self._current_plan]
        return []

    # ==================== EJECUCIÓN ====================

    def execute_plan(self, subtasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ejecuta los pasos en secuencia con manejo de fallos.

        Returns:
            Dict con {goal, steps, results, status, report}.
        """
        if not subtasks:
            return {
                "goal": self._current_goal,
                "steps": [],
                "results": {},
                "status": "empty",
                "report": "No hay pasos para ejecutar.",
            }
        if self._executor is None:
            return {
                "goal": self._current_goal,
                "steps": subtasks,
                "results": {},
                "status": "no_executor",
                "report": "Plan descompuesto pero sin ejecutor disponible.",
            }

        self._results = {}
        self._status = {}
        self._started_at = datetime.now().isoformat(timespec="seconds")

        for step in subtasks:
            step_id = step.get("id")
            self._log.append(f"Ejecutando paso {step_id}: {step.get('description')}")
            try:
                outcome = self._executor(step)
            except Exception as e:  # noqa: BLE001 - degradación elegante
                outcome = {
                    "result": f"Fallo ejecutando '{step.get('description')}': {e}",
                    "status": "error",
                }
                self._log.append(f"Paso {step_id} falló: {e}")
            if not isinstance(outcome, dict):
                outcome = {"result": str(outcome or "")}
            self._results[step_id] = outcome
            ok = outcome.get("status") in (None, "success", "ok", "done")
            self._status[step_id] = "done" if ok else "failed"

            # Si el paso falló, intentar plan alternativo. Solo se detiene
            # la secuencia si el paso y su alternativa fallan.
            if not ok:
                recovered = False
                alt = self.handle_failure(step)
                if alt is not None:
                    self._log.append(
                        f"Plan alternativo para paso {step_id}: {alt.get('description')}"
                    )
                    try:
                        alt_outcome = self._executor(alt) or {}
                        if isinstance(alt_outcome, dict):
                            alt_ok = alt_outcome.get("status") in (None, "success", "ok", "done")
                            if alt_ok:
                                self._results[step_id] = alt_outcome
                                self._status[step_id] = "done"
                                self._log.append(
                                    f"Paso {step_id} resuelto por plan alternativo"
                                )
                                recovered = True
                    except Exception as e:  # noqa: BLE001
                        self._log.append(
                            f"Plan alternativo del paso {step_id} también falló: {e}"
                        )
                if not recovered:
                    break

        self._finished_at = datetime.now().isoformat(timespec="seconds")
        failed = [s for s, st in self._status.items() if st == "failed"]
        status = "failed" if failed else "completed"
        return {
            "goal": self._current_goal,
            "steps": subtasks,
            "results": dict(self._results),
            "status": status,
            "report": self.report_progress(),
        }

    # ==================== PROGRESO ====================

    def report_progress(self) -> str:
        """Narrativa del avance del plan actual."""
        if not self._current_plan:
            return "No hay plan en curso."

        lines = []
        for step in self._current_plan:
            step_id = step.get("id")
            description = step.get("description", "?")
            state = self._status.get(step_id, "pending")
            if state == "done":
                lines.append(f"  [ok] {description}")
            elif state == "failed":
                lines.append(f"  [x] {description}")
            else:
                lines.append(f"  [ ] {description}")

        done = sum(1 for st in self._status.values() if st == "done")
        total = len(self._current_plan)
        header = f"Plan '{self._current_goal}' ({done}/{total} pasos completados):"
        return "\n".join([header] + lines)

    # ==================== FALLOS ====================

    def handle_failure(self, step: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Devuelve un plan alternativo para un paso que falló, o None.

        Reglas:
        - Si el paso dependía de un agente de datos (file/calendar/web),
          la alternativa es buscar directamente en la memoria/conversación.
        - Para pasos de resumen, no hay alternativa (no se puede improvisar).
        """
        intent = step.get("intent", "")
        agent = step.get("agent", "")

        if intent == "list_tasks":
            return {
                "id": step.get("id"),
                "agent": "memory",
                "intent": "recent_conversations",
                "params": {},
                "description": "Recuperar tus últimas notas de conversación",
                "alternative": True,
            }
        if intent == "calendar_event":
            return {
                "id": step.get("id"),
                "agent": "planner",
                "intent": "summary",
                "params": {},
                "description": "Continuar con las tareas (sin eventos)",
                "alternative": True,
            }
        if agent == "planner":
            return None
        return None

    # ==================== CONSULTAS ====================

    def get_log(self) -> List[str]:
        """Devuelve el registro de eventos del planificador."""
        return list(self._log)

    def reset(self) -> None:
        """Limpia el estado del planificador."""
        self._current_plan = []
        self._current_goal = ""
        self._results = {}
        self._status = {}
        self._log = []
        self._started_at = None
        self._finished_at = None
