"""
agents/dialog.py - Dialog Agent (SEMANA 5, FASE 3)

Charla y respuestas conversacionales:
- tell_joke: chiste (Gemini o pyjokes en espanol)
- change_name: cambiar el nombre del asistente (persistido en archivo)
- help_query: manual generado desde brain.intent_data.INTENT_CATALOG
- smalltalk: saludos, estados de animo, presentacion, etc.
- translate_text: traduccion via MyMemory API gratuita (sin key)

MODO GEMINI (si GEMINI_API_KEY esta definida):
- Usa google-generativeai con contexto de sesion (ultimas 5 interacciones).
- Si falla, degrada automaticamente al modo plantillas.

REGLAS:
- Nunca crashea por falta de API key ni de librerias opcionales.
- Todas las llamadas externas (genai, requests, pyjokes) son mockeables.
"""

import asyncio
import concurrent.futures
import os
import re
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from agents.base import AgentBase
from brain.intent_data import CATEGORIES, INTENT_CATALOG
from brain.intent_entities import EntityExtractor

# Librerías opcionales (imports seguros)
try:
    import pyjokes
    _PYJOKES_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin pyjokes
    pyjokes = None
    _PYJOKES_AVAILABLE = False

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin google-generativeai
    genai = None
    _GENAI_AVAILABLE = False

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin requests
    requests = None
    _REQUESTS_AVAILABLE = False

_MODEL_NAMES = ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro")


def _run_coro(coro: Any) -> Any:
    """Ejecuta una corrutina de memoria desde código síncrono.

    Degradación elegante: si ya existe un loop corriendo, ejecuta la
    corrutina en un hilo separado para no bloquear la arquitectura.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

_NORM = {
    "á": "a", "à": "a", "â": "a", "ä": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o", "ö": "o",
    "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "ñ": "n", "ç": "c",
}

_HELP_KEYWORDS = (
    "que puedes hacer", "que haces", "como funcionas",
    "tus funciones", "que comandos", "tus comandos", "manual",
)

# (palabras clave normalizadas, respuesta) con {name} sustituible
_SMALLTALK_RULES: List[Tuple[Tuple[str, ...], str]] = [
    (("buenos dias", "buenas tardes", "buenas noches"), "¡{name}! Buenos días. ¿En qué te ayudo?"),
    (("hola", "hello", "hey", "hi"), "¡Hola! ¿En qué puedo ayudarte?"),
    (("como estas", "como te va", "como andas"), "¡Estoy en línea y listo para ayudarte!"),
    (("quien eres", "que eres"), "Soy {name}, tu asistente personal."),
    (("como te llamas", "cual es tu nombre"), "Me llamo {name}."),
    (("gracias", "thank you", "muchas gracias"), "¡De nada! Cuando me necesites, aquí estaré."),
    (("adios", "hasta luego", "hasta pronto", "chao", "bye"), "¡Hasta pronto!"),
]

_NAME_MARKERS = (
    "cambiate el nombre a", "cambia el nombre a", "el nombre a",
    "me llamo", "te llamare", "te llamaras", "te llamo",
    "llamame", "llamate",
)

_TRANSLATE_MARKERS = (
    " al ingles", " al espanol", " al alemán", " al aleman",
    " a ingles", " a espanol", " del espanol", " del ingles",
    " al", " a ",
)

# ── Autoconciencia funcional (CONCIENCIA N4) ──

_INTROSPECTION_WHY = (
    "por que me respondiste", "por que respondiste", "por que dijiste",
    "por que contestaste", "por que me contestaste",
)
_INTROSPECTION_STATUS = (
    "que estas haciendo", "cual es tu estado", "cual es el estado",
    "en que estas", "que estas haciendo ahora", "estas ocupado",
)
_INTROSPECTION_UNKNOWN = (
    "que no sabes hacer", "que no puedes hacer", "que no haces",
    "que no sabes", "que no puedes", "que te falta",
)
_INTROSPECTION_ARCH = (
    "como funcionas", "como funciono", "como estas programado",
    "como esta construido", "como es tu arquitectura", "como estas hecho",
    "como funciona tu",
)

# Intenciones del catálogo resueltas fuera del DialogAgent (orquestador +
# agentes System/Web/File/Calendar/Voice). Se usa como respaldo cuando no hay
# memoria para calcularlo desde el estado real.
_IMPLEMENTED_ELSEWHERE: frozenset = frozenset({
    # Acciones directas del orquestador
    "time_query", "date_query", "play_music", "watch_videos", "search_info",
    "open_application", "take_screenshot", "tell_joke", "system_control",
    "change_name", "exit", "take_notes", "create_task", "set_timer",
    "watch_streaming", "play_podcast", "news_query", "directions",
    "traffic_info", "book_ride", "flight_booking", "hotel_booking",
    "weather_query",
    # WebAgent
    "get_exchange_rate", "crypto_price", "check_investments",
    # SystemAgent
    "volume_control", "open_folder", "empty_trash", "lock_session",
    # FileAgent
    "list_tasks", "complete_task", "read_file", "list_folder", "reminder_set",
    # CalendarAgent
    "calendar_event",
    # VoiceAgent
    "speak_text", "listen_voice", "calibrate_mic",
})

# Marcas de respuestas débiles para la auto-evaluación post-respuesta (N4).
_WEAK_MARKERS = (
    "en desarrollo", "no tengo implementada", "no pude", "no encontré",
    "no estoy seguro", "no tengo memoria", "no tengo disponible",
    "no tengo un tema anterior",
)


class DialogAgent(AgentBase):
    """Agente conversacional con modo Gemini opcional y plantillas."""

    def __init__(
        self,
        agent_type: str = "dialog_agent",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=agent_type, agent_type=agent_type, config=config)
        self._api_key: str = (
            (config or {}).get("gemini_api_key") or os.getenv("GEMINI_API_KEY", "")
        )
        self._memory: Optional[Any] = (config or {}).get("memory")
        self._history: Deque[Tuple[str, str]] = deque(maxlen=10)
        self._model: Optional[Any] = None
        self._assistant_name: str = self._load_name()
        self._handlers: Dict[str, Any] = {
            "tell_joke": self._joke,
            "change_name": self._change_name,
            "help_query": self._help,
            "smalltalk": self._smalltalk,
            "translate_text": self._translate,
        }

    # ==================== PUNTO DE ENTRADA ====================

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un mensaje y devuelve una respuesta conversacional.

        Returns:
            {"status": ..., "data": {"result": ...}, "agent": "dialog_agent"}
        """
        if not isinstance(message, dict):
            return self._result(
                "error", {"result": "Mensaje inválido", "source": "internal"}
            )

        intent = message.get("intent") or message.get("name") or ""
        params = message.get("parameters") or message.get("entities") or {}
        if not isinstance(params, dict):
            params = {}
        user_input = (
            message.get("text")
            or message.get("user_input")
            or message.get("input")
            or ""
        )

        handler = self._handlers.get(intent)
        if handler is None:
            data = {
                "result": f"Intención '{intent}' en desarrollo",
                "source": "internal",
            }
            data = self._self_evaluate(intent, user_input, data)
            return self._result("success", data)

        try:
            data = handler(params, user_input)
            self._remember_detected_facts(user_input)
            data = self._self_evaluate(intent, user_input, data)
            return self._result("success", data)
        except Exception as e:
            self.record_error(f"process:{intent}", e)
            return self._result(
                "error", {"intent": intent, "error": str(e), "source": "internal"}
            )

    def handle_event(self, event: Dict[str, Any]) -> None:
        """Reacciona a eventos del bus (por ahora solo registra)."""
        self.logger.debug(f"Evento recibido: {event}")

    def get_info(self) -> Dict[str, Any]:
        """Información del agente, capacidades y modo activo."""
        info = super().get_info()
        info["capabilities"] = list(self._handlers.keys())
        info["assistant_name"] = self._assistant_name
        info["gemini"] = {"enabled": self._gemini_enabled(), "has_key": bool(self._api_key)}
        info["dependencies"] = {
            "pyjokes": _PYJOKES_AVAILABLE,
            "genai": _GENAI_AVAILABLE,
            "requests": _REQUESTS_AVAILABLE,
        }
        return info

    # ==================== MODO GEMINI (opcional) ====================

    def _gemini_enabled(self) -> bool:
        """Indica si el modo Gemini puede usarse (librería + API key)."""
        return bool(_GENAI_AVAILABLE and self._api_key)

    def _with_gemini(
        self,
        intent: str,
        params: Dict[str, Any],
        user_input: str,
        fallback: Callable[[], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Genera la respuesta con Gemini; si falla, usa el fallback."""
        if not self._gemini_enabled():
            return fallback()
        try:
            text = self._gemini_chat(intent, user_input)
            if text:
                return {"result": text, "source": "gemini"}
        except Exception as e:
            self.record_error("gemini", e)
        return fallback()

    def _gemini_chat(self, intent: str, user_input: str) -> str:
        """Envía la consulta a Gemini incluyendo el contexto de sesión."""
        if self._model is None:
            genai.configure(api_key=self._api_key)
            self._model = self._create_model()
            if self._model is None:
                return ""

        parts: List[str] = []

        # Memoria episódica persistente (CONCIENCIA N1)
        persistent = self._recent_conversations(5)
        if persistent:
            parts.append("Conversaciones anteriores (memoria persistente):")
            for turn in persistent:
                parts.append(f"Usuario: {turn['user_message']}")
                parts.append(f"JARVIS: {turn['agent_response']}")

        if self._history:
            parts.append("Historial de la conversación (últimas interacciones):")
            for role, content in self._history:
                parts.append(f"{role}: {content}")

        # Memoria semántica / hechos del usuario (CONCIENCIA N2)
        facts = self._get_facts()
        if facts:
            parts.append("Datos que conozco del usuario (memoria semántica):")
            for fact in facts:
                parts.append(f"- {fact['fact_type']}: {fact['fact_value']}")

        if user_input:
            parts.append(f"Usuario: {user_input}")
        parts.append(f"(Intención detectada: {intent})")
        parts.append("Responde en español, breve y natural, como JARVIS.")
        prompt = "\n".join(parts)

        response = self._model.generate_content(prompt)
        text = getattr(response, "text", "") or ""
        if text:
            self._record_turn(user_input or "", text)
        return text

    def _create_model(self) -> Optional[Any]:
        """Crea el modelo Gemini probando nombres de modelo estables."""
        for name in _MODEL_NAMES:
            try:
                return genai.GenerativeModel(name)
            except Exception:  # pragma: no cover - nombre no disponible
                continue
        return None

    def _record_turn(self, user_text: str, assistant_text: str) -> None:
        """Guarda una interacción en el historial (máx. 5 turnos)."""
        if user_text:
            self._history.append(("Usuario", user_text))
        self._history.append(("JARVIS", assistant_text))

    def _remember_detected_facts(self, user_input: str) -> None:
        """Extrae hechos declarativos de la frase y los persiste (N2)."""
        if not user_input or self._memory is None:
            return
        try:
            facts = EntityExtractor().extract_facts(user_input)
        except Exception as e:
            self.record_error("fact_extraction", e)
            return
        for fact in facts:
            self._remember_fact(
                fact["fact_type"],
                fact["fact_value"],
                confidence=fact["confidence"],
                source=fact.get("source"),
            )

    # ==================== MEMORIA (CONCIENCIA N1/N2) ====================
    # Declaración de honestidad: la "memoria" aquí es recuperación de datos
    # reales desde SQLite, no vivencia subjetiva. Todo es observable y testeable.

    def _recent_conversations(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Últimas conversaciones persistentes, en orden antiguo → reciente."""
        if self._memory is None:
            return []
        try:
            turns = self._memory.get_recent_sync(limit) or []
        except Exception as e:
            self.record_error("memory_recent", e)
            return []
        return list(reversed(turns))

    def _get_facts(self, fact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Hechos persistentes sobre el usuario (o de un tipo concreto)."""
        if self._memory is None:
            return []
        try:
            return self._memory.get_facts_sync(fact_type) or []
        except Exception as e:
            self.record_error("memory_facts", e)
            return []

    def _remember_fact(
        self,
        fact_type: str,
        fact_value: str,
        confidence: float = 0.8,
        source: Optional[str] = None,
    ) -> None:
        """Persiste un hecho sobre el usuario en la memoria semántica."""
        if self._memory is None:
            return
        try:
            _run_coro(self._memory.save_fact(fact_type, fact_value, confidence, source))
        except Exception as e:
            self.record_error("memory_save_fact", e)

    def _summarize_recent(self) -> Dict[str, Any]:
        """Responde '¿de qué hablamos?' con datos reales de SQLite."""
        turns = self._recent_conversations(5)
        if not turns:
            return {
                "result": "Todavía no hemos hablado de nada que yo recuerde.",
                "source": "memory",
            }
        lines = []
        for turn in turns:
            when = str(turn.get("timestamp", "")).split(" ")[0]
            lines.append(
                f"- [{when}] Tú: {turn['user_message']} → Yo: {turn['agent_response']}"
            )
        return {
            "result": "Esto es de lo que hemos hablado:\n" + "\n".join(lines),
            "source": "memory",
        }

    def _search_memory(self, query: str) -> Dict[str, Any]:
        """Busca conversaciones pasadas sobre un tema ('¿recuerdas cuando X?')."""
        if self._memory is None:
            return {
                "result": "No tengo memoria disponible en este modo.",
                "source": "templates",
            }
        try:
            results = _run_coro(self._memory.search_conversations(query, limit=3)) or []
        except Exception as e:
            self.record_error("memory_search", e)
            results = []
        if not results:
            return {
                "result": f"No recuerdo haber hablado de '{query.strip()}'.",
                "source": "memory",
            }
        lines = [
            f"- Tú: {r['user_message']} → Yo: {r['agent_response']}" for r in results
        ]
        return {
            "result": "Sí, recuerdo:\n" + "\n".join(lines),
            "source": "memory",
        }

    def _answer_user_name(self) -> Dict[str, Any]:
        """Responde '¿cómo me llamo?' desde la memoria semántica."""
        facts = self._get_facts("nombre")
        if facts:
            name = facts[0]["fact_value"]
            return {
                "result": f"Claro, tu nombre es {name}.",
                "source": "memory",
            }
        return {
            "result": "Todavía no me has dicho tu nombre. ¿Cómo te llamas?",
            "source": "templates",
        }

    def _answer_preferences(self, fact_type: str = "preferencia") -> Dict[str, Any]:
        """Responde preguntas sobre gustos del usuario desde los hechos."""
        facts = self._get_facts(fact_type)
        if not facts:
            return {
                "result": "Aún no me has contado eso. ¡Cuéntame!",
                "source": "templates",
            }
        values = ", ".join(f["fact_value"] for f in facts)
        labels = {
            "preferencia": "preferencias",
            "lugar": "lugar",
            "tarea": "pendientes",
            "nombre": "nombre",
        }
        label = labels.get(fact_type, fact_type)
        return {
            "result": f"Recuerdo tus {label}: {values}.",
            "source": "memory",
        }

    @staticmethod
    def _is_user_name_question(norm: str) -> bool:
        """True si la frase pregunta por el nombre del USUARIO."""
        return any(
            k in norm
            for k in (
                "como me llamo",
                "cual es mi nombre",
                "como es mi nombre",
                "recuerdas mi nombre",
                "whats my name",
                "what is my name",
                "do you know my name",
            )
        )

    @staticmethod
    def _is_preference_question(norm: str) -> bool:
        """True si la frase pregunta por gustos del usuario."""
        return any(
            k in norm
            for k in (
                "que musica me gusta",
                "que me gusta",
                "cuales son mis preferencias",
                "que comida me gusta",
                "what music do i like",
            )
        )

    @staticmethod
    def _is_recall_question(norm: str) -> bool:
        """True si la frase pide recordar conversaciones pasadas."""
        if any(
            k in norm
            for k in (
                "de que hablamos",
                "que hablamos",
                "que hemos hablado",
                "de que me hablaste",
                "de que estuvimos hablando",
                "retomemos",
            )
        ):
            return True
        return bool(
            re.search(
                r"recuerdas cuando|te acuerdas cuando|do you remember|remember when",
                norm,
            )
        )

    # ==================== CHISTES ====================

    def _joke(self, params: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """Cuenta un chiste (Gemini o pyjokes en español)."""
        return self._with_gemini("tell_joke", params, user_input, self._template_joke)

    def _template_joke(self) -> Dict[str, Any]:
        """Chiste desde pyjokes; si no está disponible, uno fijo."""
        if _PYJOKES_AVAILABLE:
            try:
                return {"result": pyjokes.get_joke(language="es"), "source": "pyjokes"}
            except Exception as e:
                self.record_error("pyjokes", e)
        return {
            "result": "¿Qué le dice un jardinero a otro? Nos vemos en el césped.",
            "source": "templates",
        }

    # ==================== CAMBIO DE NOMBRE ====================

    def _change_name(self, params: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """Cambia el nombre del asistente y lo guarda en disco."""
        new_name = (params.get("new_name") or params.get("name") or "").strip()
        if not new_name:
            new_name = self._extract_name(user_input)
        if not new_name:
            return {"result": "¿Cómo quieres que me llame?", "source": "templates"}

        new_name = new_name.strip().strip(" ¿?¡!.,:;'\"¿").capitalize()
        self._assistant_name = new_name
        origin = self._save_name(new_name)
        self._remember_fact("nombre", new_name, confidence=0.95)
        return {
            "result": f"Listo, a partir de ahora me llamo {new_name}.",
            "source": origin,
        }

    @classmethod
    def _extract_name(cls, text: str) -> str:
        """Extrae el nombre propuesto a partir del texto del usuario."""
        low = cls._normalize(text)
        for marker in _NAME_MARKERS:
            if marker in low:
                rest = text[low.find(marker) + len(marker):].strip()
                return cls._first_word(rest)
        words = text.split()
        if not words:
            return ""
        return cls._first_word(words[-1])

    @staticmethod
    def _first_word(rest: str) -> str:
        """Devuelve la primera palabra útil de un fragmento."""
        if not rest:
            return ""
        return rest.split()[0].strip(" ¿?¡!.,:;'\"¿")

    def _name_file(self) -> str:
        """Ruta del archivo donde se persiste el nombre."""
        configured = (self.config or {}).get("assistant_name_file")
        if configured:
            return configured
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "data", "assistant_name.txt")

    def _load_name(self) -> str:
        """Carga el nombre guardado previamente (o el valor por defecto)."""
        try:
            path = self._name_file()
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    name = f.read().strip()
                if name:
                    return name
        except Exception:
            pass
        return "JARVIS"

    def _save_name(self, name: str) -> str:
        """Persiste el nombre en un archivo; falla suave a memoria."""
        try:
            path = self._name_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(name)
            return "file"
        except Exception as e:
            self.record_error("save_name", e)
            return "memory"

    # ==================== AYUDA / MANUAL ====================

    def _help(self, params: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """Manual generado desde INTENT_CATALOG (todas las intenciones)."""
        return self._build_help()

    def _build_help(self) -> Dict[str, Any]:
        """Lista todas las intenciones disponibles agrupadas por categoría."""
        if not INTENT_CATALOG:
            return {
                "result": "No tengo catálogo de comandos disponible.",
                "source": "templates",
                "count": 0,
            }

        lines: List[str] = [
            f"Soy {self._assistant_name}, tu asistente personal.",
            "Esto es lo que puedo hacer:",
        ]
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for intent in INTENT_CATALOG.values():
            groups.setdefault(str(intent.get("category", "otras")), []).append(intent)

        for category in sorted(groups):
            title = CATEGORIES.get(category, category)
            lines.append(f"\n[{title}]")
            for intent in sorted(groups[category], key=lambda i: str(i.get("name", ""))):
                examples = intent.get("variations_es") or []
                example = examples[0] if examples else f"/{intent.get('name', '')}"
                lines.append(f"- {example}   (comando: {intent.get('name', '')})")
        return {"result": "\n".join(lines), "source": "templates", "count": len(INTENT_CATALOG)}

    # ==================== SMALLTALK ====================

    def _smalltalk(self, params: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """Charla breve: saludos, estados de ánimo, presentación, memoria, etc."""
        text = (user_input or params.get("topic") or "").strip()
        if not text:
            return {"result": "Dime algo y trataré de ayudarte.", "source": "templates"}

        norm = self._normalize(text)

        # CONCIENCIA N4: preguntas de autoconciencia (por qué respondiste,
        # estado actual, límites, arquitectura)
        introspection = self._introspection_response(norm)
        if introspection is not None:
            return introspection

        # CONCIENCIA N2: preguntas sobre lo que conozco del usuario
        if self._is_user_name_question(norm):
            return self._answer_user_name()
        if self._is_preference_question(norm):
            return self._answer_preferences("preferencia")

        # CONCIENCIA N1: recuperar conversaciones pasadas (vía plantillas,
        # así funciona también sin Gemini)
        if self._is_recall_question(norm):
            return self._template_smalltalk(text)

        if "me llamo" in norm:
            return self._change_name(params, text)
        if any(re.search(rf"\b{re.escape(keyword)}\b", norm) for keyword in _HELP_KEYWORDS):
            return self._build_help()

        return self._with_gemini(
            "smalltalk", params, text, lambda: self._template_smalltalk(text)
        )

    def _template_smalltalk(self, text: str) -> Dict[str, Any]:
        """Responde con plantillas predefinidas (incluye memoria N1/N2)."""
        norm = self._normalize(text)

        # CONCIENCIA N1: recordar conversaciones pasadas
        if self._is_recall_question(norm):
            match = re.search(
                r"(?:recuerdas cuando|te acuerdas cuando|do you remember|remember when)\s+(.+)",
                text,
                flags=re.IGNORECASE,
            )
            if match:
                return self._search_memory(match.group(1))
            return self._summarize_recent()

        for keywords, response in _SMALLTALK_RULES:
            for keyword in keywords:
                if re.search(rf"\b{re.escape(keyword)}\b", norm):
                    return {
                        "result": response.format(name=self._assistant_name),
                        "source": "templates",
                    }
        return {
            "result": "No estoy seguro de haber entendido. Puedes pedirme ayuda "
                      "o decirme 'qué puedes hacer' para ver mis comandos.",
            "source": "templates",
        }

    # ==================== TRADUCCIÓN ====================

    def _translate(self, params: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """Traduce texto con MyMemory API gratuita (sin key)."""
        text = (params.get("text") or params.get("query") or "").strip()
        if not text:
            text = self._extract_translation_text(user_input)
        if not text:
            return {"result": "¿Qué texto quieres que traduzca?", "source": "templates"}

        source = (
            params.get("source_lang") or params.get("source") or params.get("from")
            or "es"
        ).strip()
        target = (
            params.get("target_lang") or params.get("target") or params.get("to")
            or "en"
        ).strip()

        if not _REQUESTS_AVAILABLE:
            return {"result": "Traducción en desarrollo", "source": "templates"}

        data = self._get_json(
            "https://api.mymemory.translated.net/get",
            {"q": text, "langpair": f"{source}|{target}"},
        )
        translated = ""
        if data:
            translated = ((data.get("responseData") or {}).get("translatedText") or "")
        if not translated:
            return {"result": "Traducción en desarrollo", "source": "templates"}
        return {"result": translated, "source": "mymemory"}

    @classmethod
    def _extract_translation_text(cls, text: str) -> str:
        """Extrae el fragmento a traducir a partir del texto libre."""
        low = cls._normalize(text)
        idx = low.find("traduce")
        if idx < 0:
            idx = low.find("translate")
            if idx < 0:
                return ""
            start = idx + len("translate")
        else:
            start = idx + len("traduce")

        rest = text[start:].strip().strip(" ¿?¡!.,:;'\"¿")
        low_rest = cls._normalize(rest)
        for marker in _TRANSLATE_MARKERS:
            m = low_rest.find(marker)
            if m > 0:
                rest = rest[:m]
                break
        return rest.strip().strip(" ¿?¡!.,:;'\"¿")

    # ==================== AUTOCONCIENCIA FUNCIONAL (CONCIENCIA N4) ====================
    # Declaración de honestidad: las respuestas se generan desde datos reales
    # (historial de decisión, catálogo, memoria), no texto fijo.

    def _introspection_response(self, norm: str) -> Optional[Dict[str, Any]]:
        """Devuelve la respuesta de introspección según la pregunta, o None."""
        if any(k in norm for k in _INTROSPECTION_WHY):
            return self._explain_last_decision()
        if any(k in norm for k in _INTROSPECTION_STATUS):
            return self._system_status()
        if any(k in norm for k in _INTROSPECTION_UNKNOWN):
            return self._unknown_intents()
        if any(k in norm for k in _INTROSPECTION_ARCH):
            return self._explain_architecture()
        return None

    def _memory_context(self, key: str) -> Optional[Any]:
        """Lee una clave del contexto de memoria, con degradación elegante."""
        if self._memory is None:
            return None
        try:
            context = _run_coro(self._memory.get_context()) or {}
        except Exception as e:
            self.record_error("introspection_context", e)
            return None
        if not isinstance(context, dict):
            return None
        return context.get(key)

    def _explain_last_decision(self) -> Dict[str, Any]:
        """Narra el proceso real de la última decisión (N4)."""
        last = self._memory_context("last_decision")
        if not last:
            return {
                "result": (
                    "Todavía no tengo un proceso reciente que explicarte. "
                    "Pídeme algo y te contaré cómo lo resolví."
                ),
                "source": "templates",
            }
        intent = last.get("intent") or "unknown"
        input_text = last.get("input") or "(sin texto)"
        confidence = last.get("confidence")
        agent = last.get("agent")
        reasoning = last.get("reasoning")

        lines = [f"Tu frase fue: \"{input_text}\"."]
        if isinstance(confidence, (int, float)):
            lines.append(
                f"Reconocí la intención '{intent}' con una confianza "
                f"del {confidence * 100:.0f}%."
            )
        else:
            lines.append(f"Reconocí la intención '{intent}'.")
        if agent:
            lines.append(f"Decidí enviarla al agente '{agent}'.")
        if reasoning:
            lines.append("Mi razonamiento fue:")
            lines.extend(f"- {line}" for line in reasoning.splitlines())
        return {
            "result": "\n".join(lines),
            "source": "memory",
            "decision": {
                "intent": intent,
                "agent": agent,
                "confidence": confidence,
            },
        }

    def _system_status(self) -> Dict[str, Any]:
        """Describe el estado real del sistema (N4)."""
        status = self._memory_context("system_status")
        if isinstance(status, dict):
            lines = [
                f"Nombre: {status.get('assistant_name')}",
                f"Estado: {status.get('state')}",
                f"Módulos listos: {'sí' if status.get('modules_ready') else 'no'}",
                f"Intenciones disponibles: {status.get('intents_available')}",
            ]
            agents = status.get("agents")
            if agents:
                lines.append(f"Agentes activos: {', '.join(agents)}")
            return {
                "result": "Mi estado actual es:\n" + "\n".join(lines),
                "source": "memory",
            }
        # Fallback honesto sin orquestador conectado
        gemini = "Gemini activo" if self._gemini_enabled() else "plantillas"
        memoria = (
            "conectada"
            if self._memory is not None
            else "no disponible en este modo"
        )
        return {
            "result": (
                f"Soy {self._assistant_name}. Motor de conversación: {gemini}. "
                f"Memoria persistente: {memoria}."
            ),
            "source": "templates",
        }

    def _capabilities(self) -> Optional[Dict[str, Any]]:
        """Capacidades reales (implementadas/pendientes) desde la memoria."""
        caps = self._memory_context("capabilities")
        if isinstance(caps, dict) and caps.get("pending"):
            return caps
        return None

    def _unknown_intents(self) -> Dict[str, Any]:
        """Lista real de intenciones sin implementar (N4)."""
        caps = self._capabilities()
        if caps is not None:
            pending = [p for p in caps.get("pending", []) if p in INTENT_CATALOG]
            source = "memory"
        else:
            implemented = set(self._handlers.keys()) | set(_IMPLEMENTED_ELSEWHERE)
            pending = sorted(
                name for name in INTENT_CATALOG if name not in implemented
            )
            source = "templates"

        if not pending:
            return {
                "result": "Tengo implementadas todas las intenciones del catálogo.",
                "source": source,
                "pending_count": 0,
                "pending": [],
            }

        lines = ["Estas intenciones aún están en desarrollo:"]
        for name in pending:
            intent = INTENT_CATALOG[name]
            variations = intent.get("variations_es") or []
            example = variations[0] if variations else f"/{name}"
            lines.append(f'- "{example}"   (comando: {name})')
        return {
            "result": "\n".join(lines),
            "source": source,
            "pending_count": len(pending),
            "pending": pending,
        }

    def _explain_architecture(self) -> Dict[str, Any]:
        """Explica la arquitectura real de Jarvis (N4)."""
        lines = [
            "Funciono en capas deterministas y testeables:",
            "1. Reconocimiento: brain/intent_processor.py (patrones regex + modelo ML).",
            "2. Decisión: brain/decision.py elige agente según confianza y contexto.",
            "3. Ejecución: agentes especializados (System, Web, Dialog, File, Calendar).",
            "4. Memoria: brain/memory.py (SQLite + RAM) guarda conversaciones y hechos.",
            "5. Orquestación: orchestrator/orchestrator.py coordina todo por eventos.",
        ]
        if self._gemini_enabled():
            lines.append("Además puedo usar Gemini para conversación libre (opcional).")
        return {
            "result": "\n".join(lines),
            "source": "templates",
        }

    def _self_evaluate(
        self,
        intent: str,
        user_input: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Auto-evaluación post-respuesta: detecta respuestas débiles (N4).

        No modifica la respuesta: adjunta la evaluación como metadata honesta
        y registra la debilidad para mejoras futuras.
        """
        if not isinstance(data, dict):
            return data
        result = data.get("result") or ""
        weak = (not result) or any(
            marker in result.lower() for marker in _WEAK_MARKERS
        )
        evaluation: Dict[str, Any] = {"intent": intent, "weak": weak}
        if weak:
            evaluation["note"] = "respuesta débil detectada"
            evaluation["suggestion"] = (
                "Puedes pedirme 'ayuda' o decir 'qué puedes hacer' "
                "para ver mis comandos."
            )
            self.logger.warning(
                f"[auto-evaluación] respuesta débil para '{intent}': {result[:80]}"
            )
        data["evaluation"] = evaluation
        return data

    # ==================== UTILIDADES ====================

    def _get_json(
        self, url: str, params: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """GET con timeout, devolviendo dict o None."""
        try:
            resp = requests.get(url, params=params or {}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.record_error("http", e)
            return None

    @staticmethod
    def _normalize(text: str) -> str:
        """Minúsculas sin tildes, para comparaciones a prueba de acentos."""
        return "".join(_NORM.get(c, c) for c in text.lower())

    @staticmethod
    def _result(status: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la respuesta estándar del agente."""
        return {"status": status, "data": data, "agent": "dialog_agent"}
