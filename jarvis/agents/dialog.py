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

import os
import re
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from agents.base import AgentBase
from brain.intent_data import CATEGORIES, INTENT_CATALOG

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
            return self._result(
                "success",
                {"result": f"Intención '{intent}' en desarrollo", "source": "internal"},
            )

        try:
            data = handler(params, user_input)
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
        if self._history:
            parts.append("Historial de la conversación (últimas interacciones):")
            for role, content in self._history:
                parts.append(f"{role}: {content}")
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
        """Charla breve: saludos, estados de ánimo, presentación, etc."""
        text = (user_input or params.get("topic") or "").strip()
        if not text:
            return {"result": "Dime algo y trataré de ayudarte.", "source": "templates"}

        norm = self._normalize(text)
        if "me llamo" in norm:
            return self._change_name(params, text)
        if any(re.search(rf"\b{re.escape(keyword)}\b", norm) for keyword in _HELP_KEYWORDS):
            return self._build_help()

        return self._with_gemini(
            "smalltalk", params, text, lambda: self._template_smalltalk(text)
        )

    def _template_smalltalk(self, text: str) -> Dict[str, Any]:
        """Responde con plantillas predefinidas."""
        norm = self._normalize(text)
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
