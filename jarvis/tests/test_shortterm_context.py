"""
test_shortterm_context.py - Tests de CONTEXTO A CORTO PLAZO (SEMANA 7, NIVEL 3)

Cubre brain/shortterm_context.py:
- Gestión de turnos (update / get_last_turn / has_context / clear)
- Resolución de elipsis ("¿y pasado mañana?" hereda la ciudad)
- Resolución de pronombres ("¿puedes cerrarlo?" refiere a YouTube)
- API del orquestador: resolve() -> {intent, entities, reason}
- Detección de anáfora sin contexto (needs_clarification)

Declaración de honestidad: son heurísticas deterministas (regex) sobre
patrones concretos; no comprensión real del lenguaje.
"""

from brain.shortterm_context import (
    CLARIFICATION_THRESHOLD,
    ShortTermContext,
    normalize,
)


def _turno_lleno():
    ctx = ShortTermContext()
    ctx.update("weather_query", {"location": "Lima"}, "clima de Lima")
    return ctx


# ==================== GESTIÓN DE TURNOS ====================

def test_sin_contexto():
    ctx = ShortTermContext()
    assert ctx.has_context() is False
    assert ctx.get_last_turn() is None
    assert ctx.resolve("¿y pasado mañana?") is None


def test_update_guarda_turno():
    ctx = ShortTermContext()
    ctx.update("weather_query", {"location": "Lima"}, "clima de Lima")
    assert ctx.has_context() is True
    last = ctx.get_last_turn()
    assert last["intent"] == "weather_query"
    assert last["entities"] == {"location": "Lima"}
    assert last["text"] == "clima de Lima"


def test_max_history_descarta_el_mas_viejo():
    ctx = ShortTermContext(max_history=2)
    ctx.update("a", {}, "uno")
    ctx.update("b", {}, "dos")
    ctx.update("c", {}, "tres")
    assert ctx.get_last_turn()["intent"] == "c"
    assert len(ctx._turns) == 2


def test_clear_limpia():
    ctx = _turno_lleno()
    ctx.clear()
    assert ctx.has_context() is False


# ==================== RESOLUCIÓN DE ELIPSIS ====================

def test_elipsis_pasado_manana():
    ctx = _turno_lleno()
    resolved = ctx.resolve("¿y pasado mañana?")
    assert resolved is not None
    assert resolved["intent"] == "weather_query"
    assert resolved["entities"] == {"location": "Lima"}
    assert "elipsis" in resolved["reason"]


def test_elipsis_alli():
    ctx = _turno_lleno()
    resolved = ctx.resolve("¿y allá?")
    assert resolved is not None
    assert resolved["intent"] == "weather_query"


def test_sin_continuacion_no_resuelve():
    ctx = _turno_lleno()
    assert ctx.resolve("hola") is None
    assert ctx.resolve("cuánto es 2+2") is None


# ==================== RESOLUCIÓN DE PRONOMBRES ====================

def test_pronombre_enclitico_cerrarlo():
    ctx = ShortTermContext()
    ctx.update("open_application", {"application": "youtube"}, "abre YouTube")
    resolved = ctx.resolve("¿puedes cerrarlo?")
    assert resolved is not None
    assert resolved["intent"] == "open_application"
    assert resolved["entities"]["application"] == "youtube"
    assert "pronombre" in resolved["reason"]


def test_pronombre_suelto_la():
    ctx = ShortTermContext()
    ctx.update("play_music", {"track": "Hotel California"}, "toca Hotel California")
    resolved = ctx.resolve("¿puedes pausarla?")
    assert resolved is not None
    assert resolved["entities"]["track"] == "Hotel California"


def test_pronombre_sin_entidades_no_resuelve():
    ctx = ShortTermContext()
    ctx.update("smalltalk", {}, "hola")
    assert ctx.resolve("¿puedes cerrarlo?") is None


def test_pronombre_sin_verbo_no_resuelve():
    ctx = ShortTermContext()
    ctx.update("open_application", {"application": "youtube"}, "abre YouTube")
    assert ctx.resolve("¿cuál es lo mejor?") is None


# ==================== CLARIFICACIÓN (anáfora sin contexto) ====================

def test_needs_clarification_sin_contexto():
    ctx = ShortTermContext()
    assert ctx.needs_clarification("¿y eso?") is True
    assert ctx.needs_clarification("¿qué hago al respecto?") is True


def test_needs_clarification_con_contexto_false():
    ctx = _turno_lleno()
    assert ctx.needs_clarification("¿y eso?") is False


def test_needs_clarification_frase_normal_false():
    ctx = ShortTermContext()
    assert ctx.needs_clarification("que hora es") is False


# ==================== CLARIFICACIÓN POR CONFIANZA/INTENT ====================

def test_needs_clarification_for_unknown():
    ctx = ShortTermContext()
    assert ctx.needs_clarification_for("unknown", 0.2) is True


def test_needs_clarification_for_weather_sin_lugar():
    ctx = ShortTermContext()
    assert ctx.needs_clarification_for("weather_query", 0.3, {}) is True


def test_needs_clarification_for_confianza_alta():
    ctx = ShortTermContext()
    assert ctx.needs_clarification_for("weather_query", 0.9, {}) is False


def test_get_clarification_question_weather():
    ctx = ShortTermContext()
    question = ctx.get_clarification_question("weather_query", {})
    assert question == "¿En qué lugar?"


def test_get_clarification_question_unknown():
    ctx = ShortTermContext()
    question = ctx.get_clarification_question("unknown", {})
    assert "decírmelo de otra forma" in question


# ==================== NORMALIZACIÓN ====================

def test_normalize_sin_tildes():
    assert normalize("¿Qué tiempo hará?") == "que tiempo hara"


def test_threshold_constante():
    assert CLARIFICATION_THRESHOLD == 0.4
