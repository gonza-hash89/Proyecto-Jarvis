"""
brain/intent_entities.py - Extractor de entidades NER (SEMANA 4, FASE 3)

Extrae información adicional (entidades) de lo que dice el usuario:

    "pon música de jazz"         -> {"genre": "jazz"}
    "envía 100 soles a María"    -> {"amount": "100", "recipient": "María"}
    "enciende las luces de la sala" -> {"room": "sala"}
    "reserva un vuelo a Cusco"   -> {"destination": "Cusco"}

Estrategia:
    1. Los slots posibles vienen del catálogo (intent_data.INTENT_CATALOG).
    2. Lexicones (géneros, artistas, apps, ciudades, idiomas, habitaciones, ...).
    3. Regex para números, montos, duraciones, horas.
    4. Captura contextual: la frase después de marcadores ("sobre", "de", ...).

Interfaz:
    extractor = EntityExtractor()
    extractor.extract("play_music", "pon música de jazz") -> {"genre": "jazz"}
"""

import re
from typing import Dict, List, Optional, Tuple

from brain.intent_data import INTENT_CATALOG, FILLERS


# ─────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────

_STOP_PREFIX = {
    "de", "del", "el", "la", "los", "las", "un", "una", "unos", "unas",
    "a", "al", "en", "para", "por", "sobre", "acerca", "hacia",
    "the", "a", "an", "of", "to", "for", "about", "at", "in",
}

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_DURATION_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(minutos?|min\b|minute|min|horas?|hr|hora\b|d[ií]as?|day|"
    r"semanas?|week|segundos?|second|s\b)"
)
_TIME_RE = re.compile(r"(?:a las |at )?(\d{1,2}):(\d{2})|a las (\d{1,2})(?:\b|:00)")
_AMOUNT_RE = re.compile(r"\$\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:soles|d[oó]lares|euros|dollars|soles)")

# ─────────────────────────────────────────────────────────────
# Lexicones (ES + EN)
# ─────────────────────────────────────────────────────────────

def _clean_words(words: List[str]) -> List[str]:
    """Normaliza palabras de FILLERS (quita prefijos 'de '/'about ', artículos)."""
    cleaned = []
    for w in words:
        w = re.sub(r"^(de|del|about|a|an|el|la|los|las|the|un|una)\s+", "", w.strip().lower())
        if w:
            cleaned.append(w)
    return sorted(set(cleaned), key=len, reverse=True)


_LEXICONS: Dict[str, List[str]] = {
    "genre": _clean_words(FILLERS["genre"] + FILLERS["genre_en"]),
    "artist": _clean_words(FILLERS["artist"] + FILLERS["artist_en"]),
    "app_name": _clean_words(FILLERS["app"] + FILLERS["app_en"]),
    "room": _clean_words(FILLERS["room"] + FILLERS["room_en"]),
    "city": _clean_words(FILLERS["city"] + FILLERS["city_en"]),
    "language": _clean_words(FILLERS["language"] + FILLERS["language_en"]),
    "contact_name": _clean_words(FILLERS["contact"] + FILLERS["contact_en"]),
    "recipient": _clean_words(FILLERS["recipient"] + FILLERS["recipient_en"]),
    "bill_type": _clean_words(FILLERS["bill"] + FILLERS["bill_en"]),
    "direction": _clean_words(FILLERS["direction_es"] + FILLERS["direction_en"]),
    "action": ["apagar", "apaga", "reiniciar", "reinicia", "bloquear", "bloquea",
               "dormir", "hibernar", "shutdown", "restart", "reboot", "lock", "sleep"],
    "coin_name": ["bitcoin", "ethereum", "dogecoin", "cardano", "solana", "litecoin", "ripple", "xrp"],
    "metric": ["calorías", "pasos", "entrenamiento", "rutina", "sueño", "horas de sueño",
               "calories", "steps", "workout", "sleep", "exercise"],
    "stat_type": ["presión arterial", "presión", "frecuencia cardíaca", "pulso", "ritmo cardíaco",
                  "blood pressure", "heart rate", "pulse"],
    "account_type": ["cuenta de ahorros", "cuenta corriente", "ahorros", "corriente", "cuenta",
                     "savings", "checking", "account"],
    "investment_type": ["acciones", "bonos", "fondos", "etf", "cripto", "crypto", "stocks", "bonds"],
    "period": ["este mes", "mes pasado", "este año", "esta semana", "mes", "semana", "año",
               "this month", "last month", "month", "week", "year"],
    "platform": ["netflix", "disney", "hbo", "amazon prime", "prime video", "youtube", "spotify"],
    "date": ["hoy", "mañana", "pasado mañana", "hoy día", "lunes", "martes", "miércoles", "jueves",
             "viernes", "sábado", "domingo", "el fin de semana", "esta noche",
             "today", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday", "this weekend", "tonight", "next week", "next month"],
    "podcast_name": _clean_words(FILLERS["podcast"] + FILLERS["podcast_en"]),
    "song": _clean_words(FILLERS["song"] + FILLERS["song_en"]),
    "currency": _clean_words(FILLERS["currency"] + FILLERS["currency_en"]),
    "format": ["png", "jpg", "jpeg", "gif", "mp4", "pdf", "pantalla", "screen", "video"],
}


# ─────────────────────────────────────────────────────────────
# Extractor
# ─────────────────────────────────────────────────────────────

class EntityExtractor:
    """Extrae entidades según los slots definidos para cada intención."""

    def __init__(self) -> None:
        self._lexicons = {k: list(v) for k, v in _LEXICONS.items()}

    # ── API pública ──

    def extract(self, intent: str, text: str) -> Dict[str, str]:
        """
        Extrae las entidades de `text` para la intención dada.

        Args:
            intent: nombre de la intención (catálogo).
            text: texto del usuario.

        Returns:
            dict con las entidades encontradas {slot: valor}.
        """
        entities: Dict[str, str] = {}
        info = INTENT_CATALOG.get(intent)
        slots = info["entities"] if info else []
        for slot in slots:
            handler = _SLOT_HANDLERS.get(slot)
            if handler is None:
                continue
            value = getattr(self, handler)(text, slot)
            if value:
                entities[slot] = value
        return entities

    def extract_all(self, text: str) -> Dict[str, str]:
        """Extrae entidades sin conocer la intención (modo exploración)."""
        entities: Dict[str, str] = {}
        for slot, handler in _SLOT_HANDLERS.items():
            value = getattr(self, handler)(text, slot)
            if value:
                entities.setdefault(slot, value)
        return entities

    # ── Hechos declarativos (CONCIENCIA N2 - memoria semántica) ──

    def extract_facts(self, text: str) -> List[Dict[str, str]]:
        """Detecta hechos declarativos del usuario a partir de su frase.

        Declaración de honestidad: esto NO es comprensión real del mundo;
        es extracción basada en patrones lingüísticos que convierte frases
        en tuplas (fact_type, fact_value) persistentes y verificables.

        Returns:
            Lista de dicts: {"fact_type", "fact_value", "confidence", "source"}.
        """
        facts: List[Dict[str, str]] = []
        if not text:
            return facts
        for fact_type, pattern, confidence in _FACT_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = self._clean(match.group(1))
            # Cortar listas ("rock y pop" -> "rock") y puntuación final
            value = re.split(r"\s+(?:y|and|e|o)\s+", value)[0].strip(" .,;:¿?¡!()")
            if value:
                facts.append({
                    "fact_type": fact_type,
                    "fact_value": value,
                    "confidence": confidence,
                    "source": "entity_extractor",
                })
        return facts

    # ── Helpers genéricos ──

    def _match_lexicon(self, text: str, key: str) -> Optional[str]:
        """Busca la palabra más larga del lexicón presente en el texto."""
        lower = text.lower()
        for word in self._lexicons.get(key, []):
            if word in lower:
                return word
        return None

    def _capture_after(self, text: str, markers: List[str]) -> Optional[str]:
        """Captura la frase que sigue al último marcador presente."""
        lower = text.lower()
        best_pos, best_len = -1, -1
        for marker in markers:
            pos = lower.find(marker)
            if pos != -1 and pos > best_pos:
                best_pos, best_len = pos, len(marker)
        if best_pos == -1:
            return None
        phrase = text[best_pos + best_len:].strip(" .,;:¿?¡!()")
        return self._clean(phrase)

    @staticmethod
    def _clean(phrase: str) -> str:
        """Limpia prefijos stop y puntuación final."""
        words = phrase.split()
        while words and words[0].lower() in _STOP_PREFIX:
            words = words[1:]
        result = " ".join(words).strip(" .,;:¿?¡!()")
        return result or None

    # ── Números y duraciones ──

    def _extract_number(self, text: str, slot: str) -> Optional[str]:
        m = _NUMBER_RE.search(text)
        return m.group(0) if m else None

    def _extract_duration(self, text: str, slot: str) -> Optional[str]:
        m = _DURATION_RE.search(text)
        return m.group(0).strip() if m else None

    def _extract_amount(self, text: str, slot: str) -> Optional[str]:
        m = _AMOUNT_RE.search(text)
        if m:
            return m.group(1) or m.group(2)
        return self._extract_number(text, slot)

    def _extract_time(self, text: str, slot: str) -> Optional[str]:
        m = _TIME_RE.search(text)
        if m:
            if m.group(1) and m.group(2):
                return f"{m.group(1)}:{m.group(2)}"
            if m.group(3):
                return f"a las {m.group(3)}"
        return None

    def _extract_date(self, text: str, slot: str) -> Optional[str]:
        return self._match_lexicon(text, "date")

    def _extract_degrees(self, text: str, slot: str) -> Optional[str]:
        return self._extract_number(text, slot)

    # ── Lexicones simples ──

    def _extract_lexicon(self, text: str, slot: str) -> Optional[str]:
        return self._match_lexicon(text, slot)

    # ── Captura contextual ──

    _TOPIC_MARKERS = ["información sobre", "sobre", "acerca de", "datos de", "en wikipedia",
                      "busca sobre", "quién es", "qué es", "investiga sobre",
                      "information about", "about", "on wikipedia", "who is", "what is", "look up"]
    _DEST_MARKERS = ["direcciones a", "cómo llego a", "cómo llego", "ruta a", "navega a",
                     "directions to", "how do i get to", "route to", "navigate to",
                     "a "]
    _TITLE_MARKERS = ["de ", "a "]
    _GAME_MARKERS = ["juego ", "jugar ", "game ", "play "]
    _DOOR_MARKERS = ["puerta ", "puerta ", "door ", "door"]
    _NAME_MARKERS = ["llámame ", "llamarme ", "llamaré ", "te llamarás ", "quiero llamarte ",
                     "cambia tu nombre a ", "call you ", "your new name is ", "your name is "]
    _TASK_MARKERS = ["recuérdame ", "alarma para ", "recordatorio para ", "que no se me olvide ",
                     "anota ", "apunta ", "agrega la tarea ", "crea una tarea para ",
                     "remind me to ", "set a reminder to ", "add the task ", "create a task to ",
                     "make a note to "]
    _SUBJECT_MARKERS = ["sobre ", "acerca de ", "con asunto ", "about ", "with subject "]
    _TEXT_MARKERS = ["traduce ", "translate ", "traducir ", "dime en "]
    _BOOK_MARKERS = ["audiolibro de ", "el audiolibro de ", "audiobook ", "the audiobook ",
                     "listen to the audiobook "]
    _PODCAST_MARKERS = ["podcast de ", "el podcast de ", "podcast "]

    def _extract_topic(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._TOPIC_MARKERS)

    def _extract_location(self, text: str, slot: str) -> Optional[str]:
        return self._match_lexicon(text, "city") or self._capture_after(text, ["en ", "in "])

    def _extract_destination(self, text: str, slot: str) -> Optional[str]:
        city = self._match_lexicon(text, "city")
        if city:
            return city
        return self._capture_after(text, self._DEST_MARKERS)

    def _extract_song_name(self, text: str, slot: str) -> Optional[str]:
        song = self._match_lexicon(text, "song")
        return song or self._capture_after(text, ["canción ", "song ", "la canción "])

    def _extract_podcast_name(self, text: str, slot: str) -> Optional[str]:
        return self._match_lexicon(text, "podcast_name") or self._capture_after(text, self._PODCAST_MARKERS)

    def _extract_book_title(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._BOOK_MARKERS)

    def _extract_game_name(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._GAME_MARKERS)

    def _extract_title(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._TITLE_MARKERS)

    def _extract_subject(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._SUBJECT_MARKERS)

    def _extract_content(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._TASK_MARKERS)

    def _extract_task(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._TASK_MARKERS)

    def _extract_task_description(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._TASK_MARKERS)

    def _extract_text(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._TEXT_MARKERS)

    def _extract_new_name(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._NAME_MARKERS)

    def _extract_door(self, text: str, slot: str) -> Optional[str]:
        return self._capture_after(text, self._DOOR_MARKERS)

    def _extract_format(self, text: str, slot: str) -> Optional[str]:
        return self._match_lexicon(text, "format")

    def _extract_currency_from(self, text: str, slot: str) -> Optional[str]:
        return self._match_lexicon(text, "currency")

    def _extract_currency_to(self, text: str, slot: str) -> Optional[str]:
        return self._match_lexicon(text, "currency")


# Tabla de despacho slot -> método
_SLOT_HANDLERS: Dict[str, str] = {
    "topic": "_extract_topic",
    "location": "_extract_location",
    "destination": "_extract_destination",
    "city": "_extract_location",
    "amount": "_extract_amount",
    "degrees": "_extract_degrees",
    "duration": "_extract_duration",
    "time": "_extract_time",
    "date": "_extract_date",
    "room": "_extract_lexicon",
    "genre": "_extract_lexicon",
    "artist": "_extract_lexicon",
    "song_name": "_extract_song_name",
    "podcast_name": "_extract_podcast_name",
    "book_title": "_extract_book_title",
    "app_name": "_extract_lexicon",
    "game_name": "_extract_game_name",
    "platform": "_extract_lexicon",
    "title": "_extract_title",
    "format": "_extract_format",
    "contact_name": "_extract_lexicon",
    "recipient": "_extract_lexicon",
    "subject": "_extract_subject",
    "content": "_extract_content",
    "task": "_extract_task",
    "task_description": "_extract_task_description",
    "language": "_extract_lexicon",
    "text": "_extract_text",
    "action": "_extract_lexicon",
    "new_name": "_extract_new_name",
    "door_name": "_extract_door",
    "direction": "_extract_lexicon",
    "metric": "_extract_lexicon",
    "stat_type": "_extract_lexicon",
    "account_type": "_extract_lexicon",
    "investment_type": "_extract_lexicon",
    "period": "_extract_lexicon",
    "bill_type": "_extract_lexicon",
    "coin_name": "_extract_lexicon",
    "currency_from": "_extract_currency_from",
    "currency_to": "_extract_currency_to",
}

# Patrones de hechos declarativos: (fact_type, regex con grupo capturador, confidence)
_FACT_PATTERNS: List[Tuple[str, str, float]] = [
    (
        "nombre",
        r"(?:me llamo|mi nombre es|my name is)\s+(\w+)",
        0.95,
    ),
    (
        "preferencia",
        r"(?:me gusta|me gustan|me encanta|i like|i love)\s+(?:el |la |los |las |the )?([\w\s]+)",
        0.80,
    ),
    (
        "lugar",
        r"(?:vivo en|soy de|i live in|i am from)\s+([\w\s]+)",
        0.85,
    ),
    (
        "tarea",
        r"(?:tengo que|debo|i have to)\s+([\w\s]+)",
        0.70,
    ),
]
