"""
brain/agent_coordinator.py - Coordinador de agentes (SEMANA 8, FASE 3)

Permite que los agentes se comuniquen entre sí a través del EventBus y
encadena tareas multi-agente mediante PIPELINES con timeout.

Funciones principales:

1. Enriquecimiento de eventos de dominio:
   - action_completed (weather_query) -> publica "weather_data_ready"
   - action_completed (create_task)   -> publica "task_completed"
   El coordinator escucha el bus, deriva eventos de dominio y guarda
   un rastro en memoria para que otros componentes reaccionen.

2. Pipelines de agentes (registro + ejecución):
   - register_pipeline("clima_completo", [web, memory, dialog])
   - run_pipeline(name, inputs, timeout): ejecuta en secuencia con
     deadline total; si se excede -> status "timeout".
   - run_pipeline_async(name, inputs, timeout): misma lógica en un
     hilo daemon, ideal para que el orquestador no se bloquee.

DECLARACION DE HONESTIDAD:
Los agentes de Semana 5 no se modifican. El coordinador solo OBSERVA
sus eventos y genera eventos derivados deterministas. Si un agente no
está registrado o el bus no existe, degrada sin romper nada.
"""

import asyncio
import concurrent.futures
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


class AgentCoordinator:
    """Coordinador que conecta agentes vía EventBus y ejecuta pipelines."""

    # eventName de action_completed -> evento de dominio derivado.
    DERIVED_EVENTS: Dict[str, str] = {
        "weather_query": "weather_data_ready",
        "create_task": "task_completed",
    }

    def __init__(
        self,
        registry: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        memory: Optional[Any] = None,
        logger: Optional[Any] = None,
        default_timeout: float = 10.0,
    ) -> None:
        self._registry = registry
        self._event_bus = event_bus
        self._memory = memory
        self._logger = logger
        self._default_timeout = default_timeout

        self._pipelines: Dict[str, List[Dict[str, Any]]] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._task_seq = 0
        self._subscribed = False
        self._last_derived: Dict[str, Dict[str, Any]] = {}

    # ==================== EVENTOS ====================

    def subscribe_events(self) -> None:
        """Se suscribe al bus para observar las acciones de los agentes."""
        if self._subscribed or self._event_bus is None:
            return
        from orchestrator.events import JarvisEvent

        self._event_bus.subscribe(JarvisEvent.ACTION_COMPLETED.value, self.handle_event)
        self._event_bus.subscribe(JarvisEvent.ACTION_FAILED.value, self.handle_event)
        self._subscribed = True
        self._log("Suscrito a eventos de acción")

    def handle_event(self, event: Any) -> None:
        """Procesa un evento del bus y deriva eventos de dominio."""
        from orchestrator.events import JarvisEvent

        name = getattr(event, "name", "") or ""
        payload = getattr(event, "payload", {}) or {}
        if name == JarvisEvent.ACTION_COMPLETED.value:
            self._on_action_completed(payload)
        elif name == JarvisEvent.ACTION_FAILED.value:
            self._on_action_failed(payload)

    def _on_action_completed(self, payload: Dict[str, Any]) -> None:
        intent = payload.get("intent") or ""
        derived = self.DERIVED_EVENTS.get(intent)
        if derived is None:
            return
        snapshot = {
            "intent": intent,
            "input": payload.get("input"),
            "result": payload.get("result"),
            "agent": payload.get("agent"),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        self._last_derived[derived] = snapshot
        self._publish(derived, snapshot)
        self._log(f"Evento derivado: {derived} (desde {intent})")
        # Persistir el rastro para que otros componentes puedan reaccionar.
        if self._memory is not None:
            self._run_async(self._memory.set_context(f"event::{derived}", snapshot))
        # Pipeline de continuación (convención "on_<intent>"): si está
        # registrada, se encadena de forma asíncrona.
        follow_up = f"on_{intent}"
        if follow_up in self._pipelines:
            self._log(f"Encadenando pipeline '{follow_up}'")
            self.run_pipeline_async(follow_up, inputs=snapshot)

    def _on_action_failed(self, payload: Dict[str, Any]) -> None:
        intent = payload.get("intent") or ""
        if intent in self.DERIVED_EVENTS:
            self._log(f"Acción '{intent}' falló; no se deriva evento de dominio")

    # ==================== PIPELINES ====================

    def register_pipeline(self, name: str, steps: List[Dict[str, Any]]) -> None:
        """Registra una pipeline (secuencia de pasos) por nombre.

        Cada paso: {"agent": "web_agent", "intent": "weather_query", "params": {...}}
        o un paso de memoria: {"agent": "memory", "operation": "set_context", "params": {...}}
        """
        if not steps:
            return
        self._pipelines[name] = [dict(s) for s in steps]

    def run_pipeline(
        self,
        name: str,
        inputs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Ejecuta una pipeline de forma síncrona con deadline total.

        Returns:
            Dict con {name, status, steps, results}.
            status: completed | failed | timeout | missing | empty
        """
        steps = self._pipelines.get(name)
        if steps is None:
            return {"name": name, "status": "missing", "steps": [], "results": {}}
        if not steps:
            return {"name": name, "status": "empty", "steps": [], "results": {}}

        task_id = self._new_task_id()
        timeout = timeout if timeout is not None else self._default_timeout
        deadline = time.monotonic() + timeout
        ctx: Dict[str, Any] = dict(inputs or {})
        results: Dict[int, Any] = {}
        status = "completed"

        for step in steps:
            step_id = step.get("id") or len(results) + 1
            if time.monotonic() > deadline:
                status = "timeout"
                self._log(f"Pipeline '{name}' excedió el timeout ({timeout}s)")
                break
            try:
                outcome = self._run_step(step, ctx)
                results[step_id] = outcome
                if isinstance(outcome, dict) and outcome.get("status") == "error":
                    status = "failed"
                    break
            except Exception as e:
                results[step_id] = {"status": "error", "error": str(e)}
                status = "failed"
                self._log(f"Paso {step_id} de '{name}' falló: {e}", "warning")
                break

        self._tasks[task_id] = {
            "name": name,
            "status": status,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "timeout": timeout,
        }
        return {
            "name": name,
            "status": status,
            "task_id": task_id,
            "steps": [dict(s) for s in steps],
            "results": results,
        }

    def run_pipeline_async(
        self,
        name: str,
        inputs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        on_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """Ejecuta una pipeline en un hilo daemon sin bloquear al llamador."""
        timeout = timeout if timeout is not None else self._default_timeout

        def _worker() -> None:
            result = self.run_pipeline(name, inputs, timeout=timeout)
            if on_done is not None:
                try:
                    on_done(result)
                except Exception as e:
                    self._log(f"Callback on_done falló: {e}", "warning")

        thread = threading.Thread(target=_worker, daemon=True, name=f"jarvis-pipeline-{name}")
        thread.start()

    def _run_step(self, step: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
        """Ejecuta un paso de pipeline (agente, memoria o memoria-contexto)."""
        agent_name = step.get("agent", "")
        intent = step.get("intent", "")
        operation = step.get("operation", "")
        params = dict(step.get("params") or {})

        # Paso de memoria (no usa el registry de agentes).
        if agent_name == "memory":
            return self._memory_step(operation, params, ctx)

        agent = self._agent_for(agent_name)
        if agent is None:
            return {"status": "error", "error": f"Agente '{agent_name}' no registrado"}
        message = {
            "intent": intent,
            "entities": params,
            "parameters": params,
            "text": params.get("text", ""),
            "user_input": params.get("text", ""),
        }
        try:
            result = agent.process(message)
            if isinstance(result, dict) and result.get("status") == "success":
                # Los datos del paso quedan disponibles para el siguiente.
                data = result.get("data") or {}
                if isinstance(data, dict):
                    ctx[intent] = data
            return result
        except Exception as e:
            self._log(f"Agente '{agent_name}' lanzó excepción: {e}", "warning")
            return {"status": "error", "error": str(e)}

    def _memory_step(self, operation: str, params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Operaciones de memoria soportadas por la pipeline."""
        if self._memory is None:
            return {"status": "error", "error": "Memoria no disponible"}
        if operation == "set_context":
            key = params.get("key") or ""
            value = params.get("value", "")
            if not key:
                return {"status": "error", "error": "Falta 'key'"}
            try:
                self._run_async(self._memory.set_context(key, value))
                ctx[f"memory::{key}"] = value
                return {"status": "success", "result": f"Contexto '{key}' guardado"}
            except Exception as e:
                return {"status": "error", "error": str(e)}
        return {"status": "error", "error": f"Operación de memoria '{operation}' no soportada"}

    def _agent_for(self, agent_name: str) -> Optional[Any]:
        """Resuelve un agente por su nombre en el registry."""
        if self._registry is None:
            return None
        try:
            return self._registry.get(agent_name)
        except Exception:
            return None

    # ==================== ESTADO ====================

    def _new_task_id(self) -> str:
        self._task_seq += 1
        return f"pipeline_{self._task_seq}"

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Devuelve el estado de una tarea de pipeline."""
        return self._tasks.get(task_id)

    def get_last_derived(self, event_name: str) -> Optional[Dict[str, Any]]:
        """Último snapshot de un evento de dominio derivado."""
        return self._last_derived.get(event_name)

    def get_status(self) -> Dict[str, Any]:
        """Estado del coordinador (pipelines registradas y tareas)."""
        return {
            "pipelines": sorted(self._pipelines.keys()),
            "tasks": len(self._tasks),
            "subscribed": self._subscribed,
            "derived_events": list(self.DERIVED_EVENTS.values()),
        }

    # ==================== UTILIDADES ====================

    def _publish(self, event_name: str, payload: Dict[str, Any]) -> None:
        """Publica un evento en el bus (si está disponible)."""
        if self._event_bus is None:
            return
        try:
            from orchestrator.events import make_event

            self._event_bus.publish(make_event(event_name, payload))
        except Exception as e:
            self._log(f"No se pudo publicar '{event_name}': {e}", "warning")

    def _log(self, message: str, level: str = "info") -> None:
        logger = self._logger
        if logger is None:
            return
        fn = getattr(logger, level, None) or getattr(logger, "info", None)
        try:
            fn(f"[coordinator] {message}")
        except Exception:
            pass

    @staticmethod
    def _run_async(coro: Any) -> Any:
        """Ejecuta una corrutina de memoria de forma segura (loop aparte)."""
        try:
            return asyncio.run(coro)
        except RuntimeError:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
