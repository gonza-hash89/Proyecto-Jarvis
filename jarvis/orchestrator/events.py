"""
events.py - Sistema de eventos de Jarvis

Arquitectura event-driven:
- Los módulos NO se llaman directamente entre sí
- Se comunican publicando eventos en un bus central
- Cualquier módulo puede suscribirse a los eventos que le interesan
- El bus garantiza orden por prioridad y trazabilidad completa

Características:
- Eventos TIPADOS con Enum (nada de strings sueltos que rompan silenciosamente)
- Cola con prioridades (PriorityQueue, thread-safe)
- Pub/Sub desacoplado
- Historial de eventos (últimos N)
- Estadísticas en tiempo real
- Singleton (get_event_bus / init_event_bus)

Filosofía: "La arquitectura es más importante que el código".
Cada módulo de Jarvis publica QUÉ pasó; nadie necesita saber QUIÉN escucha.
"""

import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from itertools import count
from queue import Empty, PriorityQueue
from typing import Any, Callable, Dict, List, Optional


# ==================== TIPOS DE EVENTOS ====================

class JarvisEvent(str, Enum):
    """Todos los eventos que pueden ocurrir en el sistema (tipado)."""

    # --- Sistema ---
    SYSTEM_STARTED = "system_started"          # Jarvis inicia
    SYSTEM_READY = "system_ready"              # Todos los módulos listos
    SYSTEM_STOPPING = "system_stopping"        # Jarvis se está apagando
    SESSION_STARTED = "session_started"        # Sesión comienza
    SESSION_ENDED = "session_ended"            # Sesión termina

    # --- Estado ---
    STATE_CHANGED = "state_changed"            # El estado de Jarvis cambió

    # --- Voz ---
    SPEAKING_STARTED = "speaking_started"      # Jarvis empezó a hablar
    SPEAKING_ENDED = "speaking_ended"          # Jarvis terminó de hablar

    # --- Usuario ---
    USER_INPUT_RECEIVED = "user_input_received"    # Input del usuario llegó
    USER_INPUT_PROCESSED = "user_input_processed"  # Input fue procesado
    USER_RESPONSE_READY = "user_response_ready"    # Respuesta lista

    # --- Intención ---
    INTENT_RECOGNITION_STARTED = "intent_recognition_started"  # Reconociendo
    INTENT_RECOGNIZED = "intent_recognized"                    # Intención detectada

    # --- Acción ---
    ACTION_EXECUTING = "action_executing"     # Ejecutando acción
    ACTION_COMPLETED = "action_completed"     # Acción completada
    ACTION_FAILED = "action_failed"           # Acción falló

    # --- Error ---
    ERROR_OCCURRED = "error_occurred"         # Error recuperable
    ERROR_CRITICAL = "error_critical"         # Error crítico


class EventPriority(Enum):
    """Niveles de prioridad de los eventos (mayor = se procesa antes)."""
    LOW = 1       # Información de fondo
    NORMAL = 2    # Flujo normal
    HIGH = 3      # Importante
    CRITICAL = 4  # Debe procesarse inmediatamente


# ==================== ESTRUCTURA DE EVENTOS ====================

@dataclass
class Event:
    """Representa un evento en el sistema.

    Se mantiene esta estructura ligera y compatible:
    - name:      nombre del evento (JarvisEvent o string libre)
    - payload:   datos asociados al evento
    - timestamp: momento en que ocurrió
    """
    name: str
    payload: Dict[str, Any]
    timestamp: datetime = datetime.now()

    def __repr__(self) -> str:
        return (
            f"Event(name={self.name}, "
            f"payload={self.payload}, "
            f"timestamp={self.timestamp.isoformat()})"
        )


def make_event(name: str, payload: Optional[Dict[str, Any]] = None) -> Event:
    """Crea un evento de forma concisa."""
    return Event(name=name, payload=payload or {})


def make_typed_event(
    event_type: JarvisEvent,
    payload: Optional[Dict[str, Any]] = None
) -> Event:
    """Crea un evento TIPADO (recomendado)."""
    return Event(name=event_type.value, payload=payload or {})


# ==================== BUS DE EVENTOS ====================

class EventBus:
    """Bus central de eventos de Jarvis (publish-subscribe).

    - Los publicadores llaman publish(event, priority)
    - Los suscriptores llaman subscribe(event_name, callback)
    - Un worker thread procesa la cola respetando prioridades
    - Soporta suscripción comodín "*" (recibe todos los eventos)
    - Guarda historial y estadísticas en tiempo real
    """

    WILDCARD = "*"

    def __init__(
        self,
        max_queue_size: int = 1000,
        max_history: int = 500,
    ):
        """
        Inicializa el bus de eventos.

        Args:
            max_queue_size: Tamaño máximo de la cola de eventos
            max_history:    Cuántos eventos mantener en historial
        """
        self.logger = logging.getLogger("Jarvis.EventBus")

        # Suscriptores: {nombre_evento: [callables]}
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = defaultdict(list)

        # Cola con prioridades: tupla (prioridad_negativa, secuencia, evento)
        self._queue: PriorityQueue = PriorityQueue(maxsize=max_queue_size)
        self._seq = count()  # Desempate FIFO dentro de la misma prioridad

        # Historial y estado
        self._history: deque = deque(maxlen=max_history)
        self._total_published = 0
        self._total_delivered = 0
        self._lock = threading.RLock()

        # Worker thread
        self.is_running = False
        self._worker_thread: Optional[threading.Thread] = None

        self.logger.info("EventBus initialized")

    # ---------- Suscripción ----------

    def subscribe(self, event_name: str, callback: Callable[[Event], None]) -> None:
        """
        Suscribe un callback a un tipo de evento.

        Args:
            event_name: Nombre del evento (JarvisEvent.value o "*" para todos)
            callback:   Función que recibe el Event y lo procesa

        Ejemplo:
            bus.subscribe(JarvisEvent.INTENT_RECOGNIZED.value, mi_listener)
        """
        with self._lock:
            self._subscribers[event_name].append(callback)
        self.logger.debug("Subscriber added for event '%s'", event_name)

    def unsubscribe(self, event_name: str, callback: Callable[[Event], None]) -> None:
        """Desuscribe un callback de un tipo de evento."""
        with self._lock:
            if callback in self._subscribers[event_name]:
                self._subscribers[event_name].remove(callback)
                self.logger.debug("Subscriber removed from event '%s'", event_name)

    # ---------- Publicación ----------

    def publish(
        self,
        event: Event,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> bool:
        """
        Publica un evento en el bus.

        Si el bus no está corriendo, entrega el evento de forma síncrona
        para no perder información. Si está corriendo, lo encola respetando
        la prioridad.

        Args:
            event:    Evento a publicar
            priority: Prioridad de procesamiento

        Returns:
            True si el evento fue aceptado
        """
        # Compatibilidad con agentes que publican mensajes crudos (dict):
        # los convertimos a Event para que el bus sea un "puerto USB" universal.
        if isinstance(event, dict):
            event = Event(
                name=event.get("name") or event.get("type", "unknown"),
                payload=event,
            )

        with self._lock:
            self._total_published += 1

        if not self.is_running:
            self._deliver(event)
            return True

        # prioridad negativa: PriorityQueue saca primero el número menor
        item = (-priority.value, next(self._seq), event)
        try:
            self._queue.put_nowait(item)
            self.logger.debug(
                "Event queued: %s (priority: %s)", event.name, priority.name
            )
            return True
        except Exception:
            self.logger.error("Event queue full. Dropping event: %s", event.name)
            return False

    # ---------- Worker thread ----------

    def start(self) -> None:
        """Inicia el worker thread que procesa la cola de eventos."""
        if self.is_running:
            self.logger.warning("EventBus already running")
            return
        self.is_running = True
        self._worker_thread = threading.Thread(
            target=self._process_loop, daemon=True, name="jarvis-eventbus"
        )
        self._worker_thread.start()
        self.logger.info("EventBus started")

    def stop(self) -> None:
        """Detiene el worker thread de forma segura."""
        self.is_running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
            self._worker_thread = None
        self.logger.info("EventBus stopped")

    def _process_loop(self) -> None:
        """Worker: procesa eventos en orden de prioridad."""
        while self.is_running:
            try:
                _, _, event = self._queue.get(timeout=1)
            except Empty:
                continue  # timeout normal
            except Exception:
                continue

            try:
                self._deliver(event)
            finally:
                self._queue.task_done()

    # ---------- Entrega ----------

    def _deliver(self, event: Event) -> None:
        """Entrega un evento a todos los suscriptores (con lock)."""
        with self._lock:
            self._history.append(event)
            self._total_delivered += 1
            listeners = list(self._subscribers.get(event.name, []))
            listeners.extend(self._subscribers.get(self.WILDCARD, []))

        for callback in listeners:
            try:
                callback(event)
            except Exception as e:  # noqa: BLE001 - un listener no rompe el bus
                self.logger.exception(
                    "Error in listener for event %s: %s", event.name, e
                )

    # ---------- Consultas ----------

    def get_history(self, limit: int = 10) -> List[Event]:
        """Retorna los últimos N eventos procesados."""
        with self._lock:
            return list(self._history)[-limit:]

    def clear_history(self) -> None:
        """Limpia el historial de eventos."""
        with self._lock:
            self._history.clear()
        self.logger.info("Event history cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas en tiempo real del bus."""
        with self._lock:
            return {
                "is_running": self.is_running,
                "queue_size": self._queue.qsize(),
                "total_published": self._total_published,
                "total_delivered": self._total_delivered,
                "subscribers_count": sum(
                    len(v) for v in self._subscribers.values()
                ),
                "history_size": len(self._history),
                "event_types": sorted(self._subscribers.keys()),
            }

    def __repr__(self) -> str:
        return (
            f"EventBus(running={self.is_running}, "
            f"queue={self._queue.qsize()}, history={len(self._history)})"
        )


# ==================== SINGLETON ====================

_event_bus: Optional[EventBus] = None


def init_event_bus() -> EventBus:
    """
    (Re)inicializa el singleton del bus de eventos.

    Útil para pruebas (aislar entre tests) o para reiniciar el sistema.
    """
    global _event_bus
    if _event_bus is not None:
        _event_bus.stop()
    _event_bus = EventBus()
    _event_bus.start()
    return _event_bus


def get_event_bus() -> EventBus:
    """Obtiene el singleton del bus de eventos (lo crea si no existe)."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
        _event_bus.start()
    return _event_bus


__all__ = [
    "JarvisEvent",
    "EventPriority",
    "Event",
    "make_event",
    "make_typed_event",
    "EventBus",
    "init_event_bus",
    "get_event_bus",
]
