"""
orchestrator.py - Orquestador central de Jarvis

Jarvis NO hace todo: COORDINA todo. Este es el director de la orquesta.

Responsabilidades:
- Inicializar todos los módulos (voz, memoria, intención, decisión)
- Coordinar el flujo completo: entrada → memoria → intención → decisión → acción
- Publicar eventos en el EventBus para trazabilidad total
- Manejar errores con estrategias de recuperación (ErrorHandler)
- Mantener el estado de Jarvis (IDLE → LISTENING → THINKING → SPEAKING)
- Ejecutar 11 acciones: hora, fecha, música, YouTube, Wikipedia,
  abrir apps, captura, chistes, control del sistema, nombre y salir

Filosofía:
- "Mejor lento y bien, que rápido y mal"
- "La arquitectura es más importante que el código"
- Cada componente se comunica por EVENTOS, no por llamadas acopladas
"""

import asyncio
import concurrent.futures
import os
import random
import re
import sys
import threading
import time
import webbrowser as wb
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

# Configurar path para importar los paquetes de jarvis
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_config
from core.logger import JarvisLogger, AgentLogger, init_logger
from core.intent_recognizer import IntentRecognizer, Intent
from brain.intent_processor import IntentProcessor, get_processor
from brain.intent_data import INTENT_CATALOG
from brain.memory import MemoryManager
from brain.shortterm_context import ShortTermContext
from brain.planner import TaskPlanner
from brain.proactive import ProactiveEngine
from brain.agent_coordinator import AgentCoordinator
from brain.decision import (
    AgentType,
    DecisionEngine,
    DecisionContext,
    Intent as DecisionIntent,
)
from agents.registry import AgentRegistry
from agents.factory import AgentFactory
from orchestrator.events import (
    Event,
    make_event,
    EventBus,
    JarvisEvent,
    EventPriority,
    get_event_bus,
    init_event_bus,
)
from orchestrator.errors import (
    ErrorSeverity,
    ErrorHandler,
    RecoveryStrategy,
    get_error_handler,
)

# ==================== LIBRERÍAS OPCIONALES (import seguras) ====================
# Jarvis debe poder iniciarse aunque falte una librería periférica.
# Cada agente/acción verifica su disponibilidad antes de usarla.

try:
    import pyttsx3
    _VOICE_AVAILABLE = True
except ImportError:  # pragma: no cover
    pyttsx3 = None
    _VOICE_AVAILABLE = False

try:
    import edge_tts
    _EDGE_TTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    edge_tts = None
    _EDGE_TTS_AVAILABLE = False

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:  # pragma: no cover
    pygame = None
    _PYGAME_AVAILABLE = False

# WebSocket server para esfera visual (opcional)
try:
    from jarvis.servidor_ws import WebSocketServer
    _WS_AVAILABLE = True
except ImportError:  # pragma: no cover
    WebSocketServer = None
    _WS_AVAILABLE = False

try:
    import speech_recognition as sr
    _SR_AVAILABLE = True
except ImportError:  # pragma: no cover
    sr = None
    _SR_AVAILABLE = False

try:
    import wikipedia
    _WIKIPEDIA_AVAILABLE = True
except ImportError:  # pragma: no cover
    wikipedia = None
    _WIKIPEDIA_AVAILABLE = False

try:
    import pyautogui
    _PYAUTOGUI_AVAILABLE = True
except ImportError:  # pragma: no cover
    pyautogui = None
    _PYAUTOGUI_AVAILABLE = False

try:
    import pyjokes
    _PYJOKES_AVAILABLE = True
except ImportError:  # pragma: no cover
    pyjokes = None
    _PYJOKES_AVAILABLE = False


# ==================== AGENTES (SEMANA 5) ====================

_AGENT_TYPES: tuple = (AgentType.SYSTEM, AgentType.WEB, AgentType.DIALOG)

# Intenciones atendidas por los agentes de Semana 5 que el DecisionEngine
# aún no mapea explícitamente. El orquestador refina el ruteo aquí para que
# deleguen al agente correcto (fallback directo si no lo manejan).
_AGENT_ROUTING: Dict[str, AgentType] = {
    "weather_query": AgentType.WEB,
    "news_query": AgentType.WEB,
    "crypto_price": AgentType.WEB,
    "get_exchange_rate": AgentType.WEB,
    "check_investments": AgentType.WEB,
    "volume_control": AgentType.SYSTEM,
    "open_folder": AgentType.SYSTEM,
    "empty_trash": AgentType.SYSTEM,
    "lock_session": AgentType.SYSTEM,
    "smalltalk": AgentType.DIALOG,
    "help_query": AgentType.DIALOG,
    "translate_text": AgentType.DIALOG,
}


# Acciones directas del orquestador (fallback cuando no hay agente dedicado).
_DIRECT_ACTION_HANDLERS: Dict[str, str] = {
    "time_query": "_action_time",
    "date_query": "_action_date",
    "play_music": "_action_play_music",
    "watch_videos": "_action_youtube",
    "search_info": "_action_wikipedia",
    "open_application": "_action_open_app",
    "take_screenshot": "_action_screenshot",
    "tell_joke": "_action_joke",
    "system_control": "_action_system_control",
    "change_name": "_action_change_name",
    "exit": "_action_exit",
    "take_notes": "_action_take_notes",
    "create_task": "_action_create_task",
    "set_timer": "_action_set_timer",
    "watch_streaming": "_action_streaming",
    "play_podcast": "_action_podcast",
    "news_query": "_action_news",
    "directions": "_action_directions",
    "traffic_info": "_action_traffic",
    "book_ride": "_action_book_ride",
    "flight_booking": "_action_flight_booking",
    "hotel_booking": "_action_hotel_booking",
    "weather_query": "_action_weather",
}


_AGENT_LABELS: Dict[str, str] = {
    "voice_agent": "el agente de voz",
    "dialog_agent": "el agente conversacional",
    "memory_agent": "el agente de memoria",
    "system_agent": "el agente de sistema",
    "web_agent": "el agente web",
    "file_agent": "el agente de archivos",
    "calendar_agent": "el agente de agenda",
    "creative_agent": "el agente creativo",
}


# Preguntas de autoconciencia (CONCIENCIA N4): se redirigen al DialogAgent.
_INTROSPECTION_MARKERS: tuple = (
    "por que me respondiste", "por que respondiste", "por que dijiste",
    "por que contestaste", "por que me contestaste",
    "que estas haciendo", "cual es tu estado", "cual es el estado",
    "en que estas", "que estas haciendo ahora",
    "que no sabes hacer", "que no puedes hacer", "que no haces",
    "que no sabes", "que no puedes",
    "como funcionas", "como funciono", "como estas programado",
    "como esta construido", "como es tu arquitectura", "como estas hecho",
)


# ==================== ESTADOS DE JARVIS ====================

class JarvisState(Enum):
    """Estados de la máquina de estados de Jarvis.

    Mapeo con la esfera visual 3D:
        IDLE (azul) → LISTENING (verde) → THINKING (amarillo) → SPEAKING (azul brillante)
    """
    IDLE = "idle"                # Esperando input
    LISTENING = "listening"      # Escuchando al usuario (micrófono)
    THINKING = "thinking"        # Procesando intención y tomando decisión
    SPEAKING = "speaking"        # Respondiendo con voz
    ERROR = "error"              # Ocurrió un error recuperable
    STOPPING = "stopping"        # Apagando sistema


# ==================== ORCHESTRATOR ====================

class Orchestrator:
    """Director central de Jarvis.

    Conecta todos los subsistemas sin acoplarlos entre sí:
    el EventBus es el sistema nervioso, el ErrorHandler el sistema inmune,
    la memoria el almacén, el intent recognizer el oído del cerebro
    y el decision engine el criterio.
    """

    def __init__(self):
        """Inicializa configuración, logging, voz y todos los módulos."""
        self.config = get_config()

        # Logging centralizado
        init_logger(self.config)
        self.logger = AgentLogger("orchestrator", agent_id="orq_001")

        # Estado del sistema
        self.state = JarvisState.IDLE
        self.is_running = True
        self.modules_ready = False

        # Voz
        self.engine = None
        self._voice_available = _VOICE_AVAILABLE
        self._sr_available = _SR_AVAILABLE
        self._edge_available = _EDGE_TTS_AVAILABLE
        self._pygame_available = _PYGAME_AVAILABLE

        # Subsistemas (se inicializan después)
        self.event_bus: Optional[EventBus] = None
        self.error_handler: Optional[ErrorHandler] = None
        self.memory: Optional[MemoryManager] = None
        self.intent_recognizer: Optional[IntentRecognizer] = None
        self.decision_engine: Optional[DecisionEngine] = None
        self.decision_context: Optional[DecisionContext] = None
        self.agent_registry: Optional[AgentRegistry] = None
        self.agent_factory: Optional[AgentFactory] = None

        # Planificador multi-paso (SEMANA 8, FASE 1)
        self.planner: Optional[TaskPlanner] = None
        self._plan_step_results: Dict[int, Dict[str, Any]] = {}
        self._plan_pending: Optional[list] = None
        self._current_goal_text: str = ""

        # Motor proactivo (SEMANA 8, FASE 2)
        self.proactive_engine: Optional[ProactiveEngine] = None

        # Coordinador de agentes (SEMANA 8, FASE 3)
        self.coordinator: Optional[AgentCoordinator] = None

        # WebSocket server para esfera visual
        self.ws_server: Optional[WebSocketServer] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None

        # Arranque completo
        self._init_voice_engine()
        self._init_modules()
        self._init_ws_server()
        self._subscribe_events()

        self.logger.info("Orchestrator inicializado correctamente")

    # ==================== INICIALIZACIÓN ====================

    def _init_voice_engine(self) -> None:
        """Inicializa el motor de voz.

        Prioridad:
            1. edge-tts (voces neurales, si está instalado).
            2. pyttsx3 (offline, voces SAPI de Windows).
            3. Modo texto (sin motor de voz).
        """
        engine_choice = getattr(self.config.voice, "engine", "edge")

        # 1. edge-tts (motor recomendado)
        if engine_choice == "edge" and _EDGE_TTS_AVAILABLE:
            try:
                if _PYGAME_AVAILABLE:
                    pygame.mixer.init()
                    self.logger.info(
                        f"Motor de voz edge-tts inicializado (voz={self.config.voice.voice})"
                    )
                    self._voice_available = True
                    return
                self.logger.warning(
                    "pygame no instalado; edge-tts no puede reproducir el audio."
                )
            except Exception as e:
                self.logger.error(f"No se pudo inicializar pygame para edge-tts: {e}")

        # 2. pyttsx3 (offline)
        if _VOICE_AVAILABLE:
            try:
                self.engine = pyttsx3.init()
                voices = self.engine.getProperty("voices")

                # Seleccionar voz según configuración (0=masculina, 1=femenina)
                voice_id = self.config.voice.voice_id
                if voices and 0 <= voice_id < len(voices):
                    self.engine.setProperty("voice", voices[voice_id].id)

                self.engine.setProperty("rate", self.config.voice.rate)
                self.engine.setProperty("volume", self.config.voice.volume)
                self._voice_available = True
                self.logger.info(
                    f"Motor de voz pyttsx3 inicializado (rate={self.config.voice.rate})"
                )
                return
            except Exception as e:
                self._voice_available = False
                self.engine = None
                self.logger.error(f"No se pudo inicializar el motor de voz: {e}")

        # 3. Sin motor
        self._voice_available = False
        self.engine = None
        self.logger.warning("Sin motor de voz disponible. Jarvis correrá en modo texto.")

    def _init_modules(self) -> None:
        """Inicializa el EventBus, ErrorHandler, Memoria, Intención y Decisión."""
        # 1. EventBus: todos los módulos se comunican por eventos
        init_event_bus()
        self.event_bus = get_event_bus()
        self.logger.info("EventBus inicializado")

        # 2. ErrorHandler: resiliencia ante fallos
        self.error_handler = get_error_handler()
        self.logger.info("ErrorHandler inicializado")

        # 3. Memoria: RAM + SQLite
        db_path = os.path.join(
            self.config.base_dir, self.config.data_dir, "jarvis_memory.db"
        )
        self.memory = MemoryManager(db_path=db_path)
        self.logger.info("MemoryManager inicializado")

        # 4. Reconocedor de intenciones (híbrido: regex + ML)
        self.intent_recognizer = IntentRecognizer()
        self.intent_processor = get_processor()
        self.logger.info(
            f"IntentRecognizer inicializado ({len(self.intent_recognizer.get_available_intents())} intenciones)"
        )
        self.logger.info(
            f"IntentProcessor híbrido inicializado ({self.intent_processor.pattern_matcher.get_intent_count()} intenciones)"
        )

        # 5. Motor de decisiones (estrategia contextual: N3)
        self.decision_engine = DecisionEngine(strategy="context_aware")
        self.decision_context = DecisionContext(
            user_id="local_user",
            session_id=f"session_{int(time.time())}",
        )
        self.logger.info("DecisionEngine inicializado (context_aware)")

        # 5b. Contexto inmediato de turno (CONCIENCIA N3)
        self.short_term_context = ShortTermContext(max_history=5)
        self.logger.info("ShortTermContext inicializado")

        # 5c. Planificador multi-paso (SEMANA 8, FASE 1)
        self.planner = TaskPlanner(
            executor=self._execute_planner_step, logger=self.logger
        )
        self.logger.info("TaskPlanner inicializado")

        # 5d. Motor proactivo (SEMANA 8, FASE 2): recordatorios, patrones, cripto.
        db_path = os.path.join(
            self.config.base_dir, self.config.data_dir, "jarvis_memory.db"
        )
        self.proactive_engine = ProactiveEngine(
            config=self.config,
            logger=self.logger,
            event_bus=self.event_bus,
            db_path=db_path,
        )
        self.proactive_engine.on_reminder = self._proactive_on_reminder
        self.proactive_engine.on_pattern = self._proactive_on_pattern
        self.proactive_engine.on_crypto = self._proactive_on_crypto
        self.logger.info("ProactiveEngine inicializado")

        # 6. Agentes (Semana 5): registry + factory + event_bus
        self._init_agents()

        # 6b. Coordinador de agentes (SEMANA 8, FASE 3): observa el bus,
        #     deriva eventos de dominio y ejecuta pipelines multi-agente.
        self.coordinator = AgentCoordinator(
            registry=self.agent_registry,
            event_bus=self.event_bus,
            memory=self.memory,
            logger=self.logger,
        )
        self.coordinator.register_pipeline(
            "on_weather_query",
            [
                {"agent": "memory", "operation": "set_context",
                 "params": {"key": "event_weather_logged", "value": "clima consultado"}},
            ],
        )
        self.coordinator.register_pipeline(
            "on_create_task",
            [
                {"agent": "memory", "operation": "set_context",
                 "params": {"key": "event_task_logged", "value": "tarea creada"}},
            ],
        )
        self.coordinator.subscribe_events()
        self.logger.info("AgentCoordinator inicializado")

        self.modules_ready = True

        # CONCIENCIA N4: exponer estado y capacidades reales en memoria
        self._store_capabilities()
        self._store_status_snapshot()

    def _init_ws_server(self) -> None:
        """Inicializa el servidor WebSocket para la esfera visual (si está disponible)."""
        if not _WS_AVAILABLE:
            self.logger.warning("servidor_ws.py no disponible. Esfera visual sin conexión.")
            return
        try:
            self.ws_server = WebSocketServer(host="localhost", port=8765)
            self.logger.info("WebSocketServer creado (puerto 8765)")
        except Exception as e:
            self.logger.error(f"No se pudo crear WebSocketServer: {e}")
            self.ws_server = None

    def _init_agents(self) -> None:
        """Crea y registra los agentes de Semana 5, asignándoles el event_bus."""
        self.agent_registry = AgentRegistry()
        self.agent_factory = AgentFactory()
        memory = getattr(self, "memory", None)
        agent_config = {"memory": memory} if memory is not None else None
        for agent_type in _AGENT_TYPES:
            agent = self.agent_factory.create(agent_type, config=agent_config)
            if agent is not None:
                agent.event_bus = self.event_bus
                self.agent_registry.register(agent)
        self.agent_registry.start_all()
        self.logger.info(
            f"{self.agent_registry.get_count()} agentes registrados e inicializados"
        )

    def _subscribe_events(self) -> None:
        """Escucha los eventos importantes para logging y observabilidad."""
        self.event_bus.subscribe(JarvisEvent.SYSTEM_STARTED.value, self._on_system_event)
        self.event_bus.subscribe(JarvisEvent.SYSTEM_READY.value, self._on_system_event)
        self.event_bus.subscribe(JarvisEvent.SYSTEM_STOPPING.value, self._on_system_event)
        self.event_bus.subscribe(JarvisEvent.STATE_CHANGED.value, self._on_state_event)
        self.event_bus.subscribe(JarvisEvent.ERROR_OCCURRED.value, self._on_error_event)
        self.event_bus.subscribe(JarvisEvent.ERROR_CRITICAL.value, self._on_error_event)
        self.logger.debug("Suscripciones a eventos registradas")

    # ==================== EVENTOS ====================

    def _publish(
        self,
        event_name: JarvisEvent,
        payload: Optional[Dict[str, Any]] = None,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        """Publica un evento tipado en el EventBus."""
        if self.event_bus:
            self.event_bus.publish(
                make_event(event_name.value, payload or {}),
                priority=priority,
            )

    def _on_system_event(self, event: Event) -> None:
        """Registra eventos de ciclo de vida del sistema."""
        self.logger.debug(f"Evento de sistema: {event.name}")

    def _on_state_event(self, event: Event) -> None:
        """Registra cambios de estado de Jarvis."""
        self.logger.debug(
            f"Cambio de estado: {event.payload.get('from')} → {event.payload.get('to')}"
        )

    def _on_error_event(self, event: Event) -> None:
        """Registra errores publicados por el ErrorHandler."""
        self.logger.warning(f"Error registrado: {event.payload.get('message')}")

    # ==================== ESTADO ====================

    def set_state(self, state: JarvisState) -> None:
        """Transiciona la máquina de estados de Jarvis."""
        if self.state == state:
            return
        previous = self.state
        self.state = state
        self.logger.debug(f"Estado: {previous.value} → {state.value}")
        self._publish(
            JarvisEvent.STATE_CHANGED,
            {"from": previous.value, "to": state.value},
            priority=EventPriority.LOW,
        )

    # ==================== UTILIDADES ASYNC ====================

    @staticmethod
    def _run_async(coro) -> Any:
        """Ejecuta una corrutina de memoria de forma segura.

        La memoria usa async I/O (run_in_executor). Como el loop principal
        de Jarvis es síncrono, resolvemos la corrutina aquí sin bloquear
        la arquitectura.
        """
        try:
            return asyncio.run(coro)
        except RuntimeError:
            # Ya existe un loop corriendo: ejecutar en un hilo separado
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()

    # ==================== LOOP PRINCIPAL ====================

    def run(self) -> None:
        """Loop principal: saluda, escucha, procesa y responde hasta detenerse."""
        self.logger.info("Jarvis iniciando...")
        self._publish(JarvisEvent.SYSTEM_STARTED, {"version": self.config.system.version})

        module_list = self._get_module_list()
        self._publish(JarvisEvent.SYSTEM_READY, {"modules": module_list})

        self._publish(
            JarvisEvent.SESSION_STARTED,
            {"session": self.decision_context.session_id},
        )

        # Iniciar servidor WebSocket en hilo separado
        if self.ws_server:
            self._ws_thread = threading.Thread(target=self._run_ws_server, daemon=True, name="jarvis-ws")
            self._ws_thread.start()
            self.logger.info("WebSocket server iniciado en hilo background")

        self._wishme()

        # SEMANA 8 FASE 2: motor proactivo en segundo plano (daemon).
        if getattr(self, "proactive_engine", None) is not None:
            self.proactive_engine.start()

        while self.is_running:
            try:
                query = self._listen()
                if query:
                    self.process_input(query)
            except KeyboardInterrupt:
                self.logger.info("Interrupción del usuario detectada")
                break
            except Exception as e:
                self.error_handler.handle(
                    exception=e,
                    operation="main_loop",
                    severity=ErrorSeverity.ERROR,
                    strategy=RecoveryStrategy.SKIP,
                )

        self.shutdown()

    def _run_ws_server(self) -> None:
        """Ejecuta el loop asyncio del servidor WebSocket en un hilo dedicado."""
        try:
            self._ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._ws_loop)
            self._ws_loop.run_until_complete(self.ws_server.start())
        except Exception as e:
            self.logger.error(f"Error en WebSocket server: {e}")

    def shutdown(self) -> None:
        """Apaga Jarvis de forma ordenada, cerrando sesión y bus."""
        # SEMANA 8 FASE 2: detener el motor proactivo antes de apagar el bus.
        if getattr(self, "proactive_engine", None) is not None:
            self.proactive_engine.stop()
        self._publish(
            JarvisEvent.SESSION_ENDED,
            {"session": self.decision_context.session_id},
        )
        self._publish(JarvisEvent.SYSTEM_STOPPING, {})
        self.stop()
        if self.event_bus:
            self.event_bus.stop()
        # Detener servidor WebSocket
        if self.ws_server and self._ws_loop:
            try:
                self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)
                if self._ws_thread:
                    self._ws_thread.join(timeout=2)
            except Exception as e:
                self.logger.warning(f"Error deteniendo WS server: {e}")
        self.logger.info("Jarvis apagado correctamente")

    def stop(self) -> None:
        """Detiene Jarvis de forma segura (bandera + motor de voz)."""
        self.is_running = False
        self.set_state(JarvisState.STOPPING)
        if self._voice_available and self.engine is not None:
            try:
                self.engine.stop()
            except Exception:
                pass
        self.logger.info("Orchestrator detenido")

    # ==================== ENTRADA Y SALIDA ====================

    def speak(self, text: str) -> None:
        """Hace que Jarvis hable (edge-tts neural, pyttsx3 o texto)."""
        if not text:
            return
        self.set_state(JarvisState.SPEAKING)
        self._publish(JarvisEvent.SPEAKING_STARTED, {})
        self.logger.info(f"[Jarvis] {text}")

        spoken = False
        engine_choice = getattr(self.config.voice, "engine", "edge")

        # 1. edge-tts (voz neural clara)
        if engine_choice == "edge" and self._edge_available and _PYGAME_AVAILABLE:
            spoken = self._speak_edge(text)

        # 2. pyttsx3 (respaldo offline)
        if not spoken and self._voice_available and self.engine is not None:
            try:
                self.engine.say(text)
                self.engine.runAndWait()
                spoken = True
            except Exception as e:
                self.error_handler.handle(
                    exception=e,
                    operation="speak",
                    severity=ErrorSeverity.ERROR,
                    strategy=RecoveryStrategy.SKIP,
                )

        # 3. Modo texto
        if not spoken:
            print(f"[{self._load_name()}] {text}")

        self._publish(JarvisEvent.SPEAKING_ENDED, {})
        self.set_state(JarvisState.IDLE)

    def _speak_edge(self, text: str) -> bool:
        """Habla con edge-tts (voz neural) y reproduce el audio con pygame."""
        try:
            import asyncio
            import tempfile
            import uuid

            voice = getattr(self.config.voice, "voice", "es-ES-AlvaroNeural")
            mp3_path = os.path.join(
                tempfile.gettempdir(), f"jarvis_speech_{uuid.uuid4().hex[:8]}.mp3"
            )

            asyncio.run(edge_tts.Communicate(text, voice).save(mp3_path))

            pygame.mixer.music.load(mp3_path)
            pygame.mixer.music.set_volume(self.config.voice.volume)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            pygame.mixer.music.unload()
            try:
                os.remove(mp3_path)
            except OSError:
                pass
            return True
        except Exception as e:
            self.logger.warning(f"edge-tts falló ({e}); usando respaldo")
            return False

    def _listen(self) -> Optional[str]:
        """
        Escucha al usuario por micrófono (español).

        Si el reconocimiento de voz no está disponible, usa entrada de texto
        para que Jarvis siga siendo funcional.
        """
        if not self._sr_available:
            try:
                text = input("👤 Tú: ")
                return text.lower().strip() or None
            except (EOFError, KeyboardInterrupt):
                return None

        self.set_state(JarvisState.LISTENING)
        recognizer = sr.Recognizer()

        try:
            with sr.Microphone() as source:
                print("Escuchando...")
                recognizer.pause_threshold = 1
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                try:
                    audio = recognizer.listen(source, timeout=self.config.voice.timeout)
                except sr.WaitTimeoutError:
                    self.speak("Tiempo agotado. Por favor intente de nuevo.")
                    return None

            print("Reconociendo...")
            query = recognizer.recognize_google(audio, language=self.config.voice.language)
            self.logger.info(f"Reconocido: {query}")
            return query.lower().strip()

        except sr.UnknownValueError:
            self.speak("Lo siento, no entendí eso.")
            return None
        except sr.RequestError:
            self.speak("El servicio de reconocimiento de voz no está disponible.")
            return None
        except Exception as e:
            self.error_handler.handle(
                exception=e,
                operation="listen",
                severity=ErrorSeverity.ERROR,
                strategy=RecoveryStrategy.SKIP,
            )
            return None
        finally:
            self.set_state(JarvisState.IDLE)

    def _wishme(self) -> None:
        """Saludo inicial según la hora del día."""
        self.speak("Bienvenido de nuevo, señor.")

        hour = datetime.now().hour
        if 4 <= hour < 12:
            self.speak("Buenos días.")
        elif 12 <= hour < 16:
            self.speak("Buenas tardes.")
        elif 16 <= hour < 24:
            self.speak("Buenas noches.")
        else:
            self.speak("Buenas noches, hasta mañana.")

        name = self._load_name()
        self.speak(f"{name} a su servicio. ¿En qué le puedo ayudar?")

    # ==================== NOMBRE DEL ASISTENTE ====================

    def _name_file(self) -> str:
        """Ruta del archivo donde se guarda el nombre del asistente."""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assistant_name.txt",
        )

    def _load_name(self) -> str:
        """Carga el nombre del asistente desde el archivo."""
        try:
            with open(self._name_file(), "r", encoding="utf-8") as file:
                name = file.read().strip()
            return name or "Jarvis"
        except (FileNotFoundError, OSError):
            return "Jarvis"

    def _save_name(self, name: str) -> None:
        """Guarda el nombre del asistente en el archivo."""
        with open(self._name_file(), "w", encoding="utf-8") as file:
            file.write(name.strip())

    # ==================== FLUJO PRINCIPAL DE PROCESAMIENTO ====================

    def process_input(self, user_input: str) -> Optional[str]:
        """
        Flujo completo de procesamiento:
            memoria → intención → decisión → acción → respuesta

        Args:
            user_input: Texto que dijo el usuario

        Returns:
            La respuesta generada (o None si no se pudo procesar)
        """
        if not user_input or not user_input.strip():
            return None
        user_input = user_input.strip()

        self.logger.info(f"Procesando input: {user_input}")
        self._publish(JarvisEvent.USER_INPUT_RECEIVED, {"input": user_input})
        self.set_state(JarvisState.THINKING)

        # 1a. Metas multi-paso (SEMANA 8, FASE 1): si el usuario pide
        #     organizar/planificar, delegamos al TaskPlanner y salimos.
        plan_response = self._maybe_run_plan(user_input)
        if plan_response is not None:
            self._store_last_decision(user_input, None, None)
            self._publish(JarvisEvent.USER_INPUT_PROCESSED, {
                "input": user_input,
                "intent": "plan",
                "response": plan_response,
            })
            self.set_state(JarvisState.IDLE)
            return plan_response

        # 1. Guardar en memoria de contexto
        self._run_async(self.memory.set_context("last_input", user_input))

        # 2. Resolver elipsis/pronombres contra el turno anterior (N3);
        #    si no aplica, reconocer intención.
        intent = self._resolve_with_context(user_input)
        if intent is None:
            intent = self._recognize_intent(user_input)

        # 3. Tomar decisión (cerebro estratégico)
        decision = None
        if intent is not None:
            decision = self.decision_engine.decide([intent])
            if decision is None:
                self.logger.warning(
                    f"Decisión rechazada (confianza bajo umbral): {intent.name}"
                )

        # 4. Ejecutar la acción correspondiente
        response: Optional[str] = None
        if intent is not None:
            response = self._execute_intent(intent, user_input, decision)
        else:
            response = self._clarify_or_default(user_input)
            self.speak(response)

        # 4b. Actualizar contexto de turno (N3) y registrar la decisión (N4)
        if intent is not None:
            self._update_short_term_context(intent, user_input)
        self._store_last_decision(user_input, intent, decision)

        # 5. Guardar la conversación en memoria persistente
        self._run_async(
            self.memory.save_conversation(
                user_message=user_input,
                agent_response=response or "",
                intent=intent.name if intent else "unknown",
            )
        )

        self._publish(JarvisEvent.USER_INPUT_PROCESSED, {
            "input": user_input,
            "intent": intent.name if intent else "unknown",
            "response": response,
        })
        self.set_state(JarvisState.IDLE)
        return response

    def _recognize_intent(self, user_input: str) -> Optional[DecisionIntent]:
        """
        Reconoce la intención del usuario con el reconocedor híbrido
        (regex + ML). Usa el reconocedor legacy como respaldo.

        Returns:
            Intent del motor de decisiones, o None si no se reconoció.
        """
        self._publish(JarvisEvent.INTENT_RECOGNITION_STARTED, {"input": user_input})

        try:
            result = self.intent_processor.recognize(user_input)

            # Frases sin sentido: la fusión híbrida con baja confianza es "unknown".
            # Antes de rendirse, comprobamos si es una pregunta de autoconciencia (N4).
            if result.name == "unknown" or (
                result.method != "pattern" and result.confidence < 0.25
            ):
                intro = self._introspection_intent(user_input)
                if intro is not None:
                    self._publish(
                        JarvisEvent.INTENT_RECOGNIZED,
                        {"intent": "smalltalk", "confidence": intro.confidence,
                         "method": "introspection"},
                    )
                    return intro
                self.logger.warning(f"Intención no reconocida: {user_input}")
                self._publish(
                    JarvisEvent.INTENT_RECOGNIZED,
                    {"intent": "unknown", "confidence": result.confidence},
                )
                return None

            intent = DecisionIntent(
                id=f"intent_{int(time.time() * 1000)}",
                name=result.name,
                confidence=result.confidence,
                parameters=result.entities,
                raw_text=user_input,
            )
            self.logger.info(
                f"Intención: {intent.name} ({intent.confidence * 100:.0f}%) "
                f"[{result.method}]"
            )
            self._publish(
                JarvisEvent.INTENT_RECOGNIZED,
                {"intent": intent.name, "confidence": intent.confidence},
            )
            return intent

        except Exception as e:
            # Fallback resiliente: si el procesador híbrido falla, intentamos
            # con el reconocedor legacy (core/intent_recognizer.py).
            self.logger.warning(
                f"IntentProcessor falló ({e}); usando reconocedor legacy"
            )
            legacy_intent = self._recognize_legacy(user_input)
            if legacy_intent is not None:
                self._publish(
                    JarvisEvent.INTENT_RECOGNIZED,
                    {
                        "intent": legacy_intent.name,
                        "confidence": legacy_intent.confidence,
                        "method": "legacy",
                    },
                )
                return legacy_intent

            self.error_handler.handle(
                exception=e,
                operation="intent_recognition",
                severity=ErrorSeverity.ERROR,
                strategy=RecoveryStrategy.SKIP,
            )
            return None

    def _recognize_legacy(self, user_input: str) -> Optional[DecisionIntent]:
        """Reconoce con el reconocedor legacy como último recurso."""
        recognizer = getattr(self, "intent_recognizer", None)
        if recognizer is None:
            return None
        try:
            result = recognizer.recognize(user_input)
        except Exception as exc:
            self.logger.error(f"Reconocedor legacy falló: {exc}")
            return None
        if result.name == "unknown" or result.confidence < 0.3:
            return None
        return DecisionIntent(
            id=f"intent_{int(time.time() * 1000)}",
            name=result.name,
            confidence=result.confidence,
            parameters=result.entities,
            raw_text=user_input,
        )

    # ==================== CONTEXTO INMEDIATO (CONCIENCIA N3) ====================

    def _resolve_with_context(self, user_input: str) -> Optional[DecisionIntent]:
        """Resuelve elipsis/pronombres contra el turno anterior (N3).

        Returns:
            Intent reconstruido con las entidades del turno anterior, o None
            si la frase no es una continuación (el flujo sigue con el
            reconocimiento normal).
        """
        stc = getattr(self, "short_term_context", None)
        if stc is None or not stc.has_context():
            return None
        try:
            resolved = stc.resolve(user_input)
        except Exception as e:
            self.logger.warning(f"No se pudo resolver contexto de turno: {e}")
            return None
        if resolved is None:
            return None
        self.logger.info(
            f"Contexto de turno aplicado: '{user_input}' → "
            f"{resolved['intent']} (razón: {resolved['reason']})"
        )
        return DecisionIntent(
            id=f"intent_{int(time.time() * 1000)}",
            name=resolved["intent"],
            confidence=0.85,
            parameters=resolved["entities"],
            raw_text=user_input,
        )

    def _update_short_term_context(
        self,
        intent: DecisionIntent,
        user_input: str,
    ) -> None:
        """Guarda el turno actual para resolver la próxima referencia (N3)."""
        stc = getattr(self, "short_term_context", None)
        if stc is None:
            return
        stc.update(intent.name, intent.parameters, user_input)

    def _clarify_or_default(self, user_input: str) -> str:
        """Si la frase es anafórica sin contexto, pide aclaración (N3)."""
        stc = getattr(self, "short_term_context", None)
        if stc is not None and stc.needs_clarification(user_input):
            return (
                f"¿A qué te refieres con '{user_input.strip()}'? "
                "Todavía no tengo un tema anterior para relacionarlo."
            )
        return "Lo siento, no entendí eso."

    # ==================== AUTOCONCIENCIA FUNCIONAL (CONCIENCIA N4) ====================

    @staticmethod
    def _is_introspection(user_input: str) -> bool:
        """True si la frase es una pregunta sobre el propio Jarvis."""
        norm = user_input.lower()
        norm = norm.replace("á", "a").replace("é", "e").replace("í", "i") \
                   .replace("ó", "o").replace("ú", "u").replace("ü", "u")
        norm = "".join(
            c for c in norm
            if c in "abcdefghijklmnopqrstuvwxyzñ "
        ).strip()
        return any(marker in norm for marker in _INTROSPECTION_MARKERS)

    def _introspection_intent(self, user_input: str) -> Optional[DecisionIntent]:
        """Convierte una pregunta de autoconciencia en intent smalltalk (N4)."""
        if not self._is_introspection(user_input):
            return None
        return DecisionIntent(
            id=f"intent_{int(time.time() * 1000)}",
            name="smalltalk",
            confidence=0.98,
            parameters={},
            raw_text=user_input,
        )

    def _store_last_decision(
        self,
        user_input: str,
        intent: Optional[DecisionIntent],
        decision: Optional[Any],
    ) -> None:
        """Expone la última decisión real en memoria para que el DialogAgent
        pueda explicarla (N4)."""
        if getattr(self, "memory", None) is None:
            return
        summary = {
            "input": user_input,
            "intent": intent.name if intent else None,
            "confidence": round(intent.confidence, 4) if intent else None,
            "agent": decision.selected_agent.value if decision else None,
            "reasoning": decision.reasoning if decision else None,
        }
        try:
            self._run_async(self.memory.set_context("last_decision", summary))
        except Exception as e:
            self.logger.warning(f"No se pudo guardar la última decisión: {e}")

    def _explain_last_decision(self) -> str:
        """Narra la última decisión real del motor (N4)."""
        engine = getattr(self, "decision_engine", None)
        if engine is None:
            return "No tengo un motor de decisiones activo en este momento."
        try:
            history = engine.get_decision_history(1)
        except Exception as e:
            self.logger.warning(f"No se pudo leer el historial: {e}")
            return "No pude leer mi historial de decisiones."
        if not history:
            return (
                "Todavía no he tomado ninguna decisión que pueda explicarte. "
                "Pídeme algo y te contaré cómo lo resolví."
            )

        decision = history[-1]
        intent = decision.intent
        label = _AGENT_LABELS.get(
            decision.selected_agent.value, decision.selected_agent.value
        )
        lines = [
            f"Tu frase fue: \"{intent.raw_text or '(sin texto)'}\".",
            f"Reconocí la intención '{intent.name}' con una confianza "
            f"del {intent.confidence * 100:.0f}%.",
            f"Decidí enviarla a {label} (confianza de decisión: "
            f"{decision.confidence * 100:.0f}%).",
            "Mi razonamiento fue:",
        ]
        reasoning = decision.reasoning or ""
        lines.extend(f"  • {line}" for line in reasoning.splitlines())
        return "\n".join(lines)

    def _compute_capabilities(self) -> Dict[str, Any]:
        """Intenciones implementadas vs. pendientes, desde el estado real."""
        implemented = set(_DIRECT_ACTION_HANDLERS.keys())
        registry = getattr(self, "agent_registry", None)
        if registry is not None:
            for agent in registry.list_all():
                handlers = getattr(agent, "_handlers", None)
                if isinstance(handlers, dict):
                    implemented.update(handlers.keys())
        pending = sorted(
            name for name in INTENT_CATALOG if name not in implemented
        )
        return {
            "implemented": sorted(implemented),
            "pending": pending,
        }

    def _store_capabilities(self) -> None:
        """Guarda las capacidades reales en memoria para el DialogAgent (N4)."""
        if getattr(self, "memory", None) is None:
            return
        try:
            self._run_async(
                self.memory.set_context("capabilities", self._compute_capabilities())
            )
        except Exception as e:
            self.logger.warning(f"No se pudieron guardar las capacidades: {e}")

    def _store_status_snapshot(self) -> None:
        """Guarda un snapshot compacto del estado para introspección (N4)."""
        if getattr(self, "memory", None) is None:
            return
        registry = getattr(self, "agent_registry", None)
        agents = []
        if registry is not None:
            agents = sorted(
                a.agent_type for a in registry.list_all()
            )
        snapshot = {
            "state": getattr(self, "state", None),
            "modules_ready": getattr(self, "modules_ready", False),
            "assistant_name": self._load_name(),
            "agents": agents,
            "intents_available": len(INTENT_CATALOG),
        }
        try:
            self._run_async(self.memory.set_context("system_status", snapshot))
        except Exception as e:
            self.logger.warning(f"No se pudo guardar el estado: {e}")

    def _execute_intent(
        self,
        intent: DecisionIntent,
        user_input: str,
        decision: Optional[Any] = None,
    ) -> Optional[str]:
        """
        Ejecuta la intención delegando en los agentes de Semana 5
        cuando existe uno que la maneje; si no, usa las acciones directas.

        Flujo:
            1. Se obtiene el AgentType desde el DecisionEngine (o la decisión
               ya tomada en process_input).
            2. Se busca el agente en el AgentRegistry.
            3. Si existe y maneja la intención → agent.process(message).
            4. Si no existe o falla → fallback a las acciones directas.
            5. Sin acción directa → mensaje "en desarrollo".

        Returns:
            La respuesta/resultado de la acción, o None si falló.
        """
        self._publish(
            JarvisEvent.ACTION_EXECUTING,
            {"intent": intent.name, "input": user_input},
        )

        # 1) Delegación a agentes (Semana 5)
        agent_type = self._agent_type_for(intent, decision)
        agent = self._find_agent_for(intent, agent_type)
        if agent is not None:
            try:
                result = agent.process(self._agent_message(intent, user_input))
                response = self._agent_response_text(result)
                if response is not None:
                    self.speak(response)
                    self._publish(
                        JarvisEvent.ACTION_COMPLETED,
                        {
                            "intent": intent.name,
                            "agent": agent.agent_type,
                            "result": result,
                        },
                    )
                    return response
            except Exception as e:
                # Degradación elegante: si el agente falla → fallback directo
                self.logger.warning(
                    f"Agente {agent.agent_type} falló para '{intent.name}': {e}"
                )
                self._publish(
                    JarvisEvent.ACTION_FAILED,
                    {
                        "intent": intent.name,
                        "agent": agent.agent_type,
                        "error": str(e),
                    },
                )

        # 2) Fallback: acciones directas para intenciones sin agente
        actions = {
            name: getattr(self, method)
            for name, method in _DIRECT_ACTION_HANDLERS.items()
        }

        handler = actions.get(intent.name)
        if handler is None:
            message = f"Aún no tengo implementada la acción '{intent.name}'."
            self.logger.warning(message)
            self.speak(message)
            self._publish(
                JarvisEvent.ACTION_COMPLETED,
                {"intent": intent.name, "skipped": True},
            )
            return message

        try:
            result = handler(user_input, intent)
            self._publish(
                JarvisEvent.ACTION_COMPLETED,
                {"intent": intent.name, "result": result},
            )
            return result
        except Exception as e:
            self._publish(
                JarvisEvent.ACTION_FAILED,
                {"intent": intent.name, "error": str(e)},
            )
            error_handler = getattr(self, "error_handler", None)
            if error_handler is not None:
                error_handler.handle(
                    exception=e,
                    operation=f"action_{intent.name}",
                    severity=ErrorSeverity.ERROR,
                    strategy=RecoveryStrategy.SKIP,
                )
            return None

    # ==================== DELEGACIÓN A AGENTES ====================

    def _agent_type_for(
        self,
        intent: DecisionIntent,
        decision: Optional[Any] = None,
    ) -> Optional[AgentType]:
        """Devuelve el AgentType responsable desde el DecisionEngine."""
        if decision is not None:
            return decision.selected_agent
        engine = getattr(self, "decision_engine", None)
        if engine is None:
            return None
        try:
            decision = engine.decide([intent])
            if decision is None:
                return None
            return decision.selected_agent
        except Exception as e:
            self.logger.warning(f"No se pudo decidir agente para '{intent.name}': {e}")
            return None

    def _find_agent_for(
        self,
        intent: DecisionIntent,
        agent_type: Optional[AgentType],
    ) -> Optional[Any]:
        """Busca en el registry un agente que maneje la intención."""
        registry = getattr(self, "agent_registry", None)
        if registry is None:
            return None

        candidate = None
        routed = _AGENT_ROUTING.get(intent.name)
        if routed is not None:
            candidate = registry.get(routed.value)
        elif agent_type is not None:
            candidate = registry.get(agent_type.value)

        if candidate is not None and self._agent_handles(candidate, intent.name):
            return candidate
        return None

    @staticmethod
    def _agent_handles(agent: Any, intent_name: str) -> bool:
        """True si el agente registra un handler para la intención."""
        handlers = getattr(agent, "_handlers", None)
        return isinstance(handlers, dict) and intent_name in handlers

    @staticmethod
    def _agent_message(
        intent: DecisionIntent,
        user_input: str,
    ) -> Dict[str, Any]:
        """Construye el mensaje estándar que recibe agent.process()."""
        return {
            "intent": intent.name,
            "entities": intent.parameters,
            "raw_input": user_input,
            "confidence": intent.confidence,
            # Aliases para compatibilidad con los agentes de Semana 5
            "parameters": intent.parameters,
            "text": user_input,
            "user_input": user_input,
        }

    @staticmethod
    def _agent_response_text(result: Any) -> Optional[str]:
        """Extrae el texto de la respuesta de un agente (o None si falló)."""
        if not isinstance(result, dict):
            return str(result) or None
        if result.get("status") != "success":
            return None
        data = result.get("data")
        if isinstance(data, dict):
            return (data.get("result") or data.get("error") or "") or None
        return str(data or "") or None

    # ==================== MOTOR PROACTIVO (S8 F2) ====================

    def _proactive_on_reminder(self, text: str) -> None:
        """El motor proactivo avisa un recordatorio vencido (hilo daemon)."""
        self.logger.info(f"Recordatorio proactivo: {text}")
        try:
            self.speak(text)
        except Exception as e:
            self.logger.warning(f"No se pudo hablar el recordatorio: {e}")

    def _proactive_on_pattern(self, text: str) -> None:
        """El motor proactivo reporta un hábito detectado."""
        self.logger.info(f"Patrón detectado: {text}")
        try:
            self.speak(text)
        except Exception as e:
            self.logger.warning(f"No se pudo hablar el patrón: {e}")

    def _proactive_on_crypto(self, text: str) -> None:
        """El motor proactivo reporta un movimiento de criptomonedas."""
        self.logger.info(f"Movimiento cripto: {text}")
        try:
            self.speak(text)
        except Exception as e:
            self.logger.warning(f"No se pudo hablar el movimiento cripto: {e}")

    # ==================== PLANIFICACIÓN MULTI-PASO (S8 F1) ====================

    def _maybe_run_plan(self, user_input: str) -> Optional[str]:
        """Detecta metas multi-paso y las ejecuta con el TaskPlanner.

        Returns:
            La respuesta hablable si era una meta de plan; None si no aplica
            (el flujo normal de intención sigue).
        """
        planner = getattr(self, "planner", None)
        if planner is None:
            return None
        subtasks = planner.decompose(user_input)
        if not subtasks:
            return None

        self._current_goal_text = user_input
        self._plan_step_results = {}
        self._plan_pending = None
        self._publish("plan_started", {
            "goal": user_input, "steps": len(subtasks),
        })
        result = planner.execute_plan(subtasks)

        if result.get("status") == "failed":
            text = "El plan no pudo completarse del todo.\n" + result.get(
                "report", "Sin reporte."
            )
            self._publish("plan_failed", {
                "goal": user_input, "report": result.get("report"),
            })
            self.speak(text)
            return text

        results = result.get("results") or {}
        final_text = None
        if results:
            last = results.get(max(results.keys())) or {}
            if isinstance(last, dict):
                data = last.get("data")
                if isinstance(data, dict):
                    final_text = data.get("result")
                final_text = final_text or last.get("result")
        text = final_text or result.get("report", "")
        self._publish("plan_finished", {
            "goal": user_input, "status": result.get("status"),
        })
        self.speak(text)
        return text

    def _execute_planner_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """Executor de pasos del plan: delega en agentes o resuelve en local."""
        agent_name = step.get("agent", "")
        intent = step.get("intent", "")
        params = step.get("params") or {}

        # Pasos de razonamiento local (no requieren agentes de datos).
        # "memory" es la alternativa de recuperación de notas (planner.py).
        if agent_name in ("planner", "memory"):
            handler = {
                "prioritize": self._planner_prioritize,
                "summary": self._planner_summary,
                "recent_conversations": self._planner_recent_conversations,
            }.get(intent)
            if handler is None:
                return {
                    "result": f"Paso de plan '{intent}' no soportado",
                    "status": "error",
                }
            outcome = handler()
        else:
            agent = self._planner_agent(agent_name)
            if agent is None:
                return {
                    "result": f"Agente '{agent_name}' no disponible",
                    "status": "error",
                }
            try:
                outcome = agent.process({
                    "intent": intent,
                    "entities": params,
                    "parameters": params,
                    "text": self._current_goal_text or "",
                    "user_input": self._current_goal_text or "",
                })
            except Exception as e:
                self.logger.warning(
                    f"Paso de plan '{intent}' falló en {agent_name}: {e}"
                )
                return {"result": str(e), "status": "error"}
            if not isinstance(outcome, dict):
                outcome = {"result": str(outcome or "")}

        self._plan_step_results[step.get("id")] = outcome
        self._publish("plan_step_completed", {
            "step_id": step.get("id"),
            "intent": intent,
            "status": outcome.get("status"),
        })
        return outcome

    def _planner_agent(self, agent_name: str) -> Optional[Any]:
        """Resuelve un agente de datos por nombre para el plan.

        Si no está registrado (arranque mínimo de Semana 5), lo crea bajo
        demanda con la AgentFactory y lo deja registrado para la sesión.
        """
        registry = getattr(self, "agent_registry", None)
        candidate = None
        if registry is not None:
            candidate = registry.get(agent_name)
        if candidate is not None:
            return candidate

        mapping = {
            "file_agent": AgentType.FILE,
            "calendar_agent": AgentType.CALENDAR,
        }
        atype = mapping.get(agent_name)
        factory = getattr(self, "agent_factory", None)
        if atype is None or factory is None:
            return None
        try:
            db_path = os.path.join(
                self.config.base_dir, self.config.data_dir, "jarvis_memory.db"
            )
            agent = factory.create(atype, config={"db_path": db_path})
            if agent is None:
                return None
            agent.event_bus = getattr(self, "event_bus", None)
            if registry is not None:
                registry.register(agent)
            return agent
        except Exception as e:
            self.logger.warning(f"No se pudo crear agente '{agent_name}': {e}")
            return None

    def _planner_prioritize(self) -> Dict[str, Any]:
        """Prioriza las tareas pendientes obtenidas en el paso anterior."""
        tasks = []
        first = self._plan_step_results.get(1) or {}
        if isinstance(first, dict):
            data = first.get("data") or {}
            if isinstance(data, dict):
                tasks = data.get("tasks") or []
        pending = [
            t for t in tasks
            if t.get("metadata", {}).get("status") != "completada"
        ]
        self._plan_pending = pending
        if not pending:
            return {"result": "No hay tareas pendientes para priorizar.",
                    "status": "success", "count": 0}
        return {
            "result": f"{len(pending)} tareas pendientes priorizadas.",
            "status": "success", "count": len(pending),
        }

    def _planner_summary(self) -> Dict[str, Any]:
        """Arma el resumen final del plan (tareas + eventos)."""
        lines = ["Te preparé el resumen:"]
        pending = getattr(self, "_plan_pending", None) or []
        if pending:
            word = "tarea pendiente" if len(pending) == 1 else "tareas pendientes"
            lines.append(f"- {len(pending)} {word}:")
            for t in pending[:5]:
                lines.append(f"  * {t['value'].get('description', '')}")
        else:
            lines.append("- No tienes tareas pendientes.")

        events = self._plan_step_results.get(2) or {}
        if isinstance(events, dict):
            data = events.get("data") or {}
            if isinstance(data, dict):
                result = data.get("result")
                if result and "event" in result.lower():
                    lines.append("- Agenda:")
                    lines.append(f"  {result}")
        text = "\n".join(lines)
        return {"result": text, "status": "success"}

    def _planner_recent_conversations(self) -> Dict[str, Any]:
        """Alternativa cuando las tareas no se pueden leer: últimas notas."""
        notes = []
        try:
            db_path = os.path.join(
                self.config.base_dir, self.config.data_dir, "jarvis_memory.db"
            )
            from brain.memory import LongTermMemory
            store = LongTermMemory(db_path)
            for row in store._search_memories_sync("", limit=500) or []:
                metadata = row.get("metadata") or {}
                value = row.get("value") or {}
                if metadata.get("type") == "note" and value.get("content"):
                    notes.append(value["content"])
        except Exception as e:
            self.logger.warning(f"No se pudo recuperar notas recientes: {e}")
        if not notes:
            return {"result": "No pude recuperar tus notas recientes.",
                    "status": "success", "count": 0}
        lines = ["Recuperé tus últimas notas:"]
        for note in notes[-3:]:
            lines.append(f"- {note}")
        return {"result": "\n".join(lines), "status": "success", "count": len(notes)}

    # ==================== ACCIONES (11) ====================

    def _action_time(self, user_input: str, intent: DecisionIntent) -> str:
        """Dice la hora actual."""
        now = datetime.now().strftime("%I:%M %p")
        text = f"La hora actual es {now}"
        self.speak(text)
        return text

    def _action_date(self, user_input: str, intent: DecisionIntent) -> str:
        """Dice la fecha actual."""
        now = datetime.now()
        text = f"La fecha actual es {now.day} de {now.strftime('%B')} de {now.year}"
        self.speak(text)
        return text

    def _action_play_music(self, user_input: str, intent: DecisionIntent) -> str:
        """Reproduce música de la carpeta Música del usuario."""
        music_dir = os.path.expanduser("~\\Music")
        if not os.path.isdir(music_dir):
            text = "No encontré la carpeta de música."
            self.speak(text)
            return text

        songs = [
            f for f in os.listdir(music_dir)
            if f.lower().endswith((".mp3", ".wav", ".flac", ".m4a"))
        ]

        # Filtrar por género si el usuario lo pidió
        genre = intent.parameters.get("genre")
        if genre:
            songs = [s for s in songs if genre.lower() in s.lower()]

        if not songs:
            text = "No se encontró ninguna canción."
            self.speak(text)
            return text

        song = random.choice(songs)
        os.startfile(os.path.join(music_dir, song))
        text = f"Reproduciendo {song}."
        self.speak(text)
        return text

    def _action_youtube(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre YouTube en el navegador."""
        wb.open("https://www.youtube.com")
        text = "Abriendo YouTube."
        self.speak(text)
        return text

    def _action_wikipedia(self, user_input: str, intent: DecisionIntent) -> str:
        """Busca información en Wikipedia."""
        if not _WIKIPEDIA_AVAILABLE:
            text = "El módulo de Wikipedia no está disponible."
            self.speak(text)
            return text

        query = intent.parameters.get("topic") or self._strip_query(
            user_input,
            ["wikipedia", "busca", "buscar", "búscame", "información", "sobre", "de"],
        )
        if not query:
            self.speak("¿Sobre qué tema quieres que busque?")
            return "Pregunta por tema"

        try:
            wikipedia.set_lang("es")
            summary = wikipedia.summary(query, sentences=2)
            self.speak(summary)
            return summary
        except wikipedia.exceptions.DisambiguationError:
            text = "Hay varios resultados. Por favor sea más específico."
            self.speak(text)
            return text
        except Exception:
            text = "No encontré nada en Wikipedia."
            self.speak(text)
            return text

    def _action_open_app(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre una aplicación (web o local)."""
        web_apps = {
            "google": "https://www.google.com",
            "youtube": "https://www.youtube.com",
            "gmail": "https://mail.google.com",
            "github": "https://github.com",
            "spotify": "https://open.spotify.com",
            "netflix": "https://www.netflix.com",
            "twitch": "https://www.twitch.tv",
            "twitter": "https://twitter.com",
            "wikipedia": "https://es.wikipedia.org",
            "maps": "https://maps.google.com",
            "chatgpt": "https://chat.openai.com",
            "whatsapp": "https://web.whatsapp.com",
        }
        local_apps = {
            "notepad": "notepad",
            "bloc de notas": "notepad",
            "calculadora": "calc",
            "calc": "calc",
            "explorador": "explorer",
            "cmd": "cmd",
            "powershell": "powershell",
            "paint": "mspaint",
            "administrador de tareas": "taskmgr",
        }

        app = intent.parameters.get("application") or self._strip_query(
            user_input,
            ["abre el", "abre la", "abre", "abrir", "lanza", "ejecuta", "el", "la"],
        )
        if not app:
            self.speak("¿Qué aplicación quieres que abra?")
            return "Pregunta por aplicación"

        app_lower = app.lower()

        if app_lower in web_apps:
            wb.open(web_apps[app_lower])
            text = f"Abriendo {app_lower}."
            self.speak(text)
            return text

        if app_lower in local_apps:
            os.startfile(local_apps[app_lower])
            text = f"Abriendo {app_lower}."
            self.speak(text)
            return text

        try:
            os.startfile(app_lower)
            text = f"Abriendo {app_lower}."
            self.speak(text)
            return text
        except Exception:
            text = f"No encontré la aplicación {app_lower}."
            self.speak(text)
            return text

    def _action_screenshot(self, user_input: str, intent: DecisionIntent) -> Optional[str]:
        """Toma una captura de pantalla y la guarda en Pictures."""
        if not _PYAUTOGUI_AVAILABLE:
            text = "El módulo de captura de pantalla no está disponible."
            self.speak(text)
            return text

        try:
            img = pyautogui.screenshot()
            file_name = f"captura_{int(time.time())}.png"
            path = os.path.join(os.path.expanduser("~"), "Pictures", file_name)
            img.save(path)
            text = f"Captura guardada en {path}."
            self.speak(text)
            return text
        except Exception as e:
            self.error_handler.handle(
                exception=e,
                operation="screenshot",
                severity=ErrorSeverity.ERROR,
                strategy=RecoveryStrategy.SKIP,
            )
            return None

    def _action_joke(self, user_input: str, intent: DecisionIntent) -> Optional[str]:
        """Cuenta un chiste en español."""
        if not _PYJOKES_AVAILABLE:
            text = "El módulo de chistes no está disponible."
            self.speak(text)
            return text

        try:
            joke = pyjokes.get_joke(language="es")
            self.speak(joke)
            return joke
        except Exception as e:
            self.error_handler.handle(
                exception=e,
                operation="joke",
                severity=ErrorSeverity.ERROR,
                strategy=RecoveryStrategy.SKIP,
            )
            return None

    def _action_system_control(self, user_input: str, intent: DecisionIntent) -> str:
        """Controla el sistema: apagar, reiniciar, bloquear o suspender."""
        action = intent.parameters.get("action", "apagar")

        if "reiniciar" in user_input or "reinicia" in user_input or action == "reiniciar":
            self.speak("Reiniciando el sistema. ¡Hasta pronto!")
            os.system("shutdown /r /f /t 1")
            return "Reiniciando sistema"

        if "bloquear" in user_input or "bloquea" in user_input or action == "bloquear":
            self.speak("Bloqueando el equipo.")
            os.system("rundll32 user32.dll,LockWorkStation")
            return "Bloqueando equipo"

        if "dormir" in user_input or "suspender" in user_input or action == "dormir":
            self.speak("Poniendo el equipo en suspensión.")
            os.system("rundll32 powrprof.dll,SetSuspendState 0,1,0")
            return "Equipo en suspensión"

        self.speak("Apagando el sistema. ¡Hasta luego!")
        os.system("shutdown /s /f /t 1")
        return "Apagando sistema"

    def _action_change_name(self, user_input: str, intent: DecisionIntent) -> Optional[str]:
        """Permite al usuario cambiar el nombre del asistente."""
        self.speak("¿Cómo le gustaría llamarme?")
        name = self._listen()
        if not name:
            self.speak("Lo siento, no pude escuchar eso.")
            return None

        self._save_name(name)
        text = f"De acuerdo, a partir de ahora me llamaré {name}."
        self.speak(text)
        return text

    def _action_exit(self, user_input: str, intent: DecisionIntent) -> str:
        """Desconecta a Jarvis de forma amigable."""
        self.speak("Desconectándome. ¡Que tenga un excelente día!")
        self.is_running = False
        return "exit"

    # ==================== ACCIONES NUEVAS (SEMANA 4) ====================

    def _action_take_notes(self, user_input: str, intent: DecisionIntent) -> str:
        """Guarda una nota en un archivo de notas."""
        note = intent.parameters.get("content") or intent.parameters.get("task")
        if not note:
            self.speak("¿Qué quieres que anote?")
            return "Pregunta por contenido de nota"

        path = self._notes_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as file:
            file.write(f"- [{datetime.now().strftime('%Y-%m-%d %H:%M')}] {note}\n")
        text = f"Nota guardada: {note}"
        self.speak(text)
        return text

    def _action_create_task(self, user_input: str, intent: DecisionIntent) -> str:
        """Agrega una tarea a la lista de pendientes."""
        task = intent.parameters.get("task_description") or intent.parameters.get("task")
        if not task:
            self.speak("¿Qué tarea quieres agregar?")
            return "Pregunta por tarea"

        path = self._tasks_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as file:
            file.write(f"- [ ] {task}\n")
        text = f"Tarea agregada: {task}"
        self.speak(text)
        return text

    def _action_set_timer(self, user_input: str, intent: DecisionIntent) -> str:
        """Programa un temporizador que avisa al cumplirse."""
        seconds = self._parse_duration(user_input, intent.parameters.get("duration"))
        if seconds <= 0:
            seconds = 60
            unit = "minuto"
            amount = 1
        else:
            amount, unit = self._describe_duration(seconds)

        self.speak(f"Temporizador de {amount} {unit}. ¡Avisaré cuando termine!")
        threading.Timer(seconds, self._timer_finished, args=[amount, unit]).start()
        return f"Temporizador programado: {amount} {unit}"

    def _timer_finished(self, amount: int, unit: str) -> None:
        """Callback del temporizador: avisa que terminó."""
        message = f"¡Tiempo! Han pasado {amount} {unit}."
        self.logger.info(f"[Jarvis] {message}")
        print(f"[Jarvis] {message}")
        if self._voice_available and self.engine is not None:
            try:
                self.engine.say(message)
                self.engine.runAndWait()
            except Exception:
                pass

    def _action_streaming(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre la plataforma de streaming pedida."""
        platform = (intent.parameters.get("platform") or "").lower()
        urls = {
            "netflix": "https://www.netflix.com",
            "prime": "https://www.primevideo.com",
            "prime video": "https://www.primevideo.com",
            "amazon prime": "https://www.primevideo.com",
            "disney": "https://www.disneyplus.com",
            "hbo": "https://www.hbomax.com",
            "max": "https://www.max.com",
        }
        url = urls.get(platform, "https://www.netflix.com")
        target = platform or "Netflix"
        wb.open(url)
        text = f"Abriendo {target}."
        self.speak(text)
        return text

    def _action_podcast(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre la búsqueda del podcast en Spotify."""
        query = intent.parameters.get("podcast_name") or ""
        if query:
            wb.open(f"https://open.spotify.com/search/{query.replace(' ', '%20')}")
            text = f"Buscando el podcast {query} en Spotify."
        else:
            wb.open("https://open.spotify.com/search/podcast")
            text = "Abriendo la sección de podcasts en Spotify."
        self.speak(text)
        return text

    def _action_news(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre las noticias (Google News)."""
        topic = intent.parameters.get("topic")
        url = (
            f"https://news.google.com/search?q={topic.replace(' ', '%20')}"
            if topic else "https://news.google.com"
        )
        wb.open(url)
        text = f"Abriendo las noticias{' de ' + topic if topic else ''}."
        self.speak(text)
        return text

    def _action_directions(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre Google Maps con la ruta al destino."""
        destination = intent.parameters.get("destination") or intent.parameters.get("location")
        if not destination:
            self.speak("¿A dónde quieres ir?")
            return "Pregunta por destino"
        wb.open(f"https://www.google.com/maps/dir/?api=1&destination={destination.replace(' ', '+')}")
        text = f"Abriendo la ruta hacia {destination}."
        self.speak(text)
        return text

    def _action_traffic(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre el tráfico de Google Maps."""
        location = intent.parameters.get("location")
        url = (
            f"https://www.google.com/maps/search/traffic+{location.replace(' ', '+')}"
            if location else "https://www.google.com/maps/search/traffic"
        )
        wb.open(url)
        text = f"Abriendo el tráfico{' en ' + location if location else ''}."
        self.speak(text)
        return text

    def _action_book_ride(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre Uber para pedir un viaje."""
        wb.open("https://www.uber.com/es/mobile/")
        self.speak("Abriendo Uber.")
        return "Abriendo Uber"

    def _action_flight_booking(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre Google Flights con el destino."""
        destination = intent.parameters.get("destination") or intent.parameters.get("location")
        url = (
            f"https://www.google.com/travel/flights?q=flights+to+{destination.replace(' ', '+')}"
            if destination else "https://www.google.com/travel/flights"
        )
        wb.open(url)
        text = f"Buscando vuelos{' a ' + destination if destination else ''}."
        self.speak(text)
        return text

    def _action_hotel_booking(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre la búsqueda de hoteles del destino."""
        destination = intent.parameters.get("destination") or intent.parameters.get("location")
        url = (
            f"https://www.google.com/search?q=hoteles+en+{destination.replace(' ', '+')}"
            if destination else "https://www.google.com/search?q=hoteles"
        )
        wb.open(url)
        text = f"Buscando hoteles{' en ' + destination if destination else ''}."
        self.speak(text)
        return text

    def _action_weather(self, user_input: str, intent: DecisionIntent) -> str:
        """Abre el clima del lugar en el buscador."""
        location = intent.parameters.get("location") or intent.parameters.get("city")
        url = (
            f"https://www.google.com/search?q=clima+{location.replace(' ', '+')}"
            if location else "https://www.google.com/search?q=clima+hoy"
        )
        wb.open(url)
        text = f"Abriendo el clima{' en ' + location if location else ' de hoy'}."
        self.speak(text)
        return text

    def _notes_path(self) -> str:
        return os.path.join(
            self.config.base_dir, self.config.data_dir, "notas.md"
        )

    def _tasks_path(self) -> str:
        return os.path.join(
            self.config.base_dir, self.config.data_dir, "tareas.txt"
        )

    def _parse_duration(self, user_input: str, entity_duration: Optional[str]) -> int:
        """Convierte '5 minutos' / 'una hora' a segundos."""
        raw = entity_duration or user_input
        m = re.search(r"(\d+)\s*(segundos?|minutos?|horas?|min|hr|s|m|h)", raw, re.IGNORECASE)
        if not m:
            # 'una hora' o 'media hora'
            if "hora" in raw.lower():
                return 3600
            if "minuto" in raw.lower():
                return 60
            return 0
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith(("s",)):
            return amount
        if unit.startswith(("m",)):
            return amount * 60
        return amount * 3600

    @staticmethod
    def _describe_duration(seconds: int):
        if seconds % 3600 == 0:
            return seconds // 3600, "hora" if seconds // 3600 == 1 else "horas"
        if seconds % 60 == 0:
            return seconds // 60, "minuto" if seconds // 60 == 1 else "minutos"
        return seconds, "segundos"

    # ==================== HELPERS ====================

    @staticmethod
    def _strip_query(user_input: str, words) -> str:
        """Elimina palabras de relleno del input para quedarse con la consulta."""
        query = user_input
        for word in sorted(words, key=len, reverse=True):
            query = query.replace(word, " ")
        return " ".join(query.split()).strip(" ¿?¡!.,:-")

    def _get_module_list(self) -> list:
        """Lista de módulos inicializados."""
        modules = [
            "event_bus",
            "error_handler",
            "memory",
            "intent_recognizer",
            "intent_processor",
            "decision_engine",
            "agents",
        ]
        if self.ws_server:
            modules.append("websocket_server")
        return modules

    # ==================== ESTADO DEL SISTEMA ====================

    def get_status(self) -> Dict[str, Any]:
        """Estado completo del sistema (para debugging y UI)."""
        memory_stats = None
        if self.memory:
            try:
                memory_stats = self._run_async(self.memory.get_stats())
            except Exception:
                memory_stats = None

        registry = getattr(self, "agent_registry", None)
        agents_status = []
        if registry is not None:
            for agent in registry.list_all():
                agents_status.append({
                    "type": agent.agent_type,
                    "active": agent.is_active,
                    "initialized": bool(getattr(agent, "initialized", False)),
                    "capabilities": sorted(getattr(agent, "_handlers", {}).keys()),
                })

        return {
            "name": self.config.system.name,
            "version": self.config.system.version,
            "state": self.state.value,
            "is_running": self.is_running,
            "modules_ready": self.modules_ready,
            "session_id": self.decision_context.session_id,
            "voice_available": self._voice_available,
            "speech_recognition_available": self._sr_available,
            "assistant_name": self._load_name(),
            "agents": agents_status,
            "modules": {
                "event_bus": self.event_bus.get_stats() if self.event_bus else None,
                "error_handler": self.error_handler.get_stats() if self.error_handler else None,
                "memory": memory_stats,
                "intent_recognizer": (
                    len(self.intent_recognizer.get_available_intents())
                    if self.intent_recognizer else 0
                ),
                "intent_processor": (
                    self.intent_processor.get_stats()
                    if self.intent_processor else None
                ),
                "decision_history": (
                    len(self.decision_engine.get_decision_history())
                    if self.decision_engine else 0
                ),
                "websocket_server": {
                    "running": self.ws_server is not None,
                    "clients": len(self.ws_server.clients) if self.ws_server else 0,
                    "port": 8765
                } if self.ws_server else None,
                "agents": registry.get_count() if registry else 0,
            },
        }

    def __repr__(self) -> str:
        return f"Orchestrator(state={self.state.value}, running={self.is_running})"


# ==================== SINGLETON (bajo demanda) ====================
# No se instancia al importar para evitar efectos secundarios
# (inicializar voz y hilos en cada import). Se crea con get_orchestrator().

default_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Obtiene (o crea) la instancia única del orquestador."""
    global default_orchestrator
    if default_orchestrator is None:
        default_orchestrator = Orchestrator()
    return default_orchestrator


if __name__ == "__main__":
    orchestrator = Orchestrator()
    try:
        orchestrator.run()
    except KeyboardInterrupt:
        orchestrator.stop()
