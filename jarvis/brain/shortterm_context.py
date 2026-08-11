"""
brain/shortterm_context.py - Contexto a corto plazo (SEMANA 7, NIVEL 3)

Memoria de trabajo del ultimo turno: guarda (intent, entities, texto) y
resuelve referencias del lenguaje (elipsis y pronombres) usando el turno
anterior. Tambien detecta ambiguedad real que requiere aclaracion.

DECLARACION DE HONESTIDAD:
Esto NO es comprension real del lenguaje ni teoria de la mente. Son
heurísticas deterministicas sobre patrones (regex) que resuelven casos
concretos de elipsis/pronombre. Todo es observable y testeable.
"""

import re
from collections import deque
from typing import Any, Dict, List, Optional


_NORM = {
    "á": "a", "à": "a", "â": "a", "ä": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o", "ö": "o",
    "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "ñ": "n", "ç": "c", "¿": "", "?": "", "¡": "", "!": "",
    "·": "", "•": "", "–": "", "—": "",
}


# Umbral de confianza por debajo del cual se puede pedir aclaracion.
CLARIFICATION_THRESHOLD = 0.4

# Intenciones genericas/ambiguas: si llegan con baja confianza, pedir aclaracion.
_AMBIGUOUS_INTENTS = {"smalltalk", "help_query", "unknown"}

# Parametros obligatorios por intencion (para detectar ambiguedad real).
_REQUIRED_PARAMS: Dict[str, List[str]] = {
    "weather_query": ["location"],
    "create_task": ["task"],
    "send_email": ["recipient", "subject"],
    "calendar_event": ["date"],
    "take_notes": ["content"],
    "set_timer": ["duration"],
}

# Preguntas de aclaracion por slot faltante.
_SLOT_QUESTIONS: Dict[str, str] = {
    "location": "¿En qué lugar?",
    "recipient": "¿A quién se lo envío?",
    "subject": "¿Cuál es el asunto?",
    "content": "¿Qué quieres que anote?",
    "task": "¿Qué tarea quieres que registre?",
    "date": "¿Para qué fecha?",
    "duration": "¿Por cuánto tiempo?",
}

# Marcadores de elipsis temporal/espacial.
_ELLIPSIS_PATTERNS = [
    re.compile(r"\b(y|e)\s+(allá|alla|ahí|ahi|allí|alli|pasado mañana|pasado manana|luego|despues|también|tambien)\b"),
    re.compile(r"\b(allá|alla|ahí|ahi|allí|alli)\b"),
    re.compile(r"\b(pasado mañana|pasado manana)\b"),
]

# Pronombres de objeto que pueden referir a una entidad del turno anterior.
# Cubre el pronombre suelto ("¿la cierras?") y el enclítico ("cerrarla").
_PRONOUN_PATTERN = re.compile(
    r"\b(lo|la|los|las|eso|esa|ese)\b|\b\w+(lo|la|los|las)\b"
)
# Verbos de accion que delatan referencia a algo ya mencionado.
_ACTION_VERBS = (
    "cerrar", "abrir", "detener", "parar", "pausar", "continuar",
    "reproducir", "tocar", "buscar", "borrar", "eliminar", "guardar",
    "close", "open", "stop", "pause", "play", "delete", "save",
)

# Frases anafóricas que requieren contexto previo (si no lo hay, pedir aclaración).
_ANAPHORA_MARKERS = re.compile(
    r"\b(eso|eso mismo|lo mismo|al respecto|sobre eso|ahí|ahi|allá|alla)\b"
)


def normalize(text: str) -> str:
    """Normaliza texto: minusculas, sin tildes, sin puntuacion extrana."""
    norm = text.lower()
    for k, v in _NORM.items():
        norm = norm.replace(k, v)
    return norm


class ShortTermContext:
    """Contexto del ultimo turno + resolucion de referencias (N3)."""

    def __init__(self, max_history: int = 5) -> None:
        self._turns: deque = deque(maxlen=max_history)

    # ────────── GESTION DE TURNOS ──────────

    def update(self, intent: str, entities: Dict[str, Any], text: str = "") -> None:
        """Guarda el ultimo turno (intent + entidades + texto)."""
        self._turns.append({
            "intent": intent,
            "entities": dict(entities or {}),
            "text": text,
        })

    def get_last_turn(self) -> Optional[Dict[str, Any]]:
        """Devuelve el turno anterior (o None si no hay contexto)."""
        return self._turns[-1] if self._turns else None

    def has_context(self) -> bool:
        """True si hay al menos un turno previo."""
        return len(self._turns) > 0

    def clear(self) -> None:
        """Limpia el contexto (nueva sesion)."""
        self._turns.clear()

    # ────────── RESOLUCION DE REFERENCIAS (punto de entrada del orquestador) ──────────

    def resolve(self, text: str) -> Optional[Dict[str, Any]]:
        """Resuelve elipsis y pronombres contra el turno anterior (N3).

        Returns:
            Dict con {intent, entities, reason} si el texto es una
            continuación del turno anterior, o None si no aplica.
        """
        last = self.get_last_turn()
        if last is None or not text:
            return None

        resolved = self.resolve_ellipsis(text, last)
        if resolved is not None:
            return {
                "intent": resolved["intent"],
                "entities": resolved["entities"],
                "reason": "elipsis del turno anterior",
            }

        resolved = self.resolve_pronouns(text, last)
        if resolved is not None:
            return {
                "intent": resolved["intent"],
                "entities": resolved["entities"],
                "reason": "pronombre referido al turno anterior",
            }

        return None

    def needs_clarification(self, text: str) -> bool:
        """True si la frase es anafórica/elíptica pero NO hay contexto previo."""
        if not text or self.has_context():
            return False
        norm = normalize(text)
        return bool(_ANAPHORA_MARKERS.search(norm))

    # ────────── RESOLUCION DE ELIPSIS ──────────

    def resolve_ellipsis(self, text: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Resuelve elipsis: hereda intent/entidades del turno anterior.

        Ejemplo:
            turno 1: "clima de Lima"  -> intent=weather_query, entities={location: Lima}
            turno 2: "¿y pasado mañana?" -> devuelve {intent, entities de Lima}

        Devuelve un dict con {intent, entities, confidence_boost} o None.
        """
        ctx = context or self.get_last_turn()
        if not ctx or not text:
            return None
        norm = normalize(text)
        if not any(p.search(norm) for p in _ELLIPSIS_PATTERNS):
            return None
        return {
            "intent": ctx.get("intent"),
            "entities": dict(ctx.get("entities") or {}),
            "confidence_boost": 0.15,
        }

    # ────────── RESOLUCION DE PRONOMBRES ──────────

    def resolve_pronouns(self, text: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Resuelve pronombres: "¿puedes cerrarlo?" refiere a la entidad previa.

        Ejemplo:
            turno 1: "abre YouTube" -> entities={application: youtube}
            turno 2: "¿puedes cerrarlo?" -> devuelve {intent, entities con youtube}

        Devuelve un dict con {intent, entities, confidence_boost} o None.
        """
        ctx = context or self.get_last_turn()
        if not ctx or not text:
            return None
        norm = normalize(text)
        if not _PRONOUN_PATTERN.search(norm):
            return None
        if not any(v in norm for v in _ACTION_VERBS):
            return None
        entities = dict(ctx.get("entities") or {})
        if not entities:
            return None
        return {
            "intent": ctx.get("intent"),
            "entities": entities,
            "confidence_boost": 0.15,
        }

    # ────────── CLARIFICACION ──────────

    def needs_clarification_for(self, intent: str, confidence: float, parameters: Optional[Dict[str, Any]] = None) -> bool:
        """True si la confianza es baja (<0.4) y hay ambiguedad real.

        Ambiguedad real = intent generico/unknown, o faltan parametros obligatorios.
        """
        if confidence >= CLARIFICATION_THRESHOLD:
            return False
        if intent in _AMBIGUOUS_INTENTS:
            return True
        required = _REQUIRED_PARAMS.get(intent, [])
        params = parameters or {}
        return any(not params.get(p) for p in required)

    def get_clarification_question(self, intent: str = "", parameters: Optional[Dict[str, Any]] = None) -> str:
        """Pregunta especifica para la ambiguedad detectada."""
        if intent == "unknown":
            return "No entendí del todo qué necesitas. ¿Puedes decírmelo de otra forma?"
        required = _REQUIRED_PARAMS.get(intent, [])
        params = parameters or {}
        for slot in required:
            if not params.get(slot):
                return _SLOT_QUESTIONS.get(slot, f"¿Qué valor tiene {slot}?")
        return "No estoy seguro de qué quieres hacer. ¿Puedes darme más detalles?"
