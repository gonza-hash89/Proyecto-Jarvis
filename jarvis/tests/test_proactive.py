"""
test_proactive.py - SEMANA 8, FASE 2: ProactiveEngine

Cubre recordatorios vencidos (una sola notificación), detección de
patrones/hábitos y monitoreo de criptomonedas con fetch inyectado.
Sin hilos en la mayoría de los tests: se llaman los métodos síncronos.
"""

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.memory import LongTermMemory
from brain.proactive import ProactiveEngine, _iso_parse


def _tmp_db():
    return os.path.join(tempfile.mkdtemp(prefix="jarvis_proactive_test_"),
                        "jarvis_memory.db")


def _engine(db_path=None, fetch_price=None, crypto_enabled=True, event_bus=None):
    return ProactiveEngine(
        db_path=db_path or _tmp_db(),
        fetch_price=fetch_price,
        crypto_enabled=crypto_enabled,
        event_bus=event_bus,
    )


def _add_reminder(db_path, message, when):
    store = LongTermMemory(db_path)
    store._save_sync(
        f"reminder::{message}",
        {"message": message, "when": when.isoformat()},
        {"type": "reminder", "status": "pendiente"},
        "high",
    )


def _add_conversation(db_path, user_message, intent, timestamp=None):
    import sqlite3

    store = LongTermMemory(db_path)
    store._save_conversation_sync(user_message, "ok", intent)
    if timestamp is not None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE conversations SET timestamp = ? WHERE user_message = ?",
                (timestamp, user_message),
            )


# ==================== RECORDATORIOS ====================

def test_check_reminders_notifica_vencido():
    db_path = _tmp_db()
    past = datetime.now() - timedelta(minutes=5)
    _add_reminder(db_path, "tomar agua", past)
    engine = _engine(db_path)
    due = engine.check_reminders()
    assert len(due) == 1
    assert due[0]["message"] == "tomar agua"


def test_check_reminders_no_repite():
    db_path = _tmp_db()
    past = datetime.now() - timedelta(minutes=5)
    _add_reminder(db_path, "reunión", past)
    engine = _engine(db_path)
    assert len(engine.check_reminders()) == 1
    assert engine.check_reminders() == []


def test_check_reminders_futuro_no_notifica():
    db_path = _tmp_db()
    future = datetime.now() + timedelta(hours=1)
    _add_reminder(db_path, "mañana", future)
    engine = _engine(db_path)
    assert engine.check_reminders() == []


def test_check_reminders_sin_datos():
    engine = _engine()
    assert engine.check_reminders() == []


def test_check_reminders_publica_evento_y_callback():
    events = []

    class _Bus:
        def publish(self, event, priority=None):
            events.append(event.name)

    db_path = _tmp_db()
    _add_reminder(db_path, "aviso", datetime.now() - timedelta(minutes=1))
    engine = _engine(db_path, event_bus=_Bus())
    spoken = []
    engine.on_reminder = lambda text: spoken.append(text)
    engine.check_reminders()
    assert "reminder_due" in events
    assert spoken and "aviso" in spoken[0]


# ==================== PATRONES ====================

def test_detect_patterns_encuentra_habito():
    db_path = _tmp_db()
    # 3 peticiones de weather_query a las 8h → patrón en franja 08:00-09:59.
    for i in range(3):
        _add_conversation(db_path, f"clima {i}", "weather_query",
                          f"2026-08-0{i + 1} 08:15:00")
    engine = _engine(db_path)
    patterns = engine.detect_patterns(threshold=3)
    assert len(patterns) == 1
    assert patterns[0]["intent"] == "weather_query"
    assert patterns[0]["slot"] == 8
    assert patterns[0]["count"] == 3


def test_detect_patterns_no_duplica_reportes():
    db_path = _tmp_db()
    for i in range(3):
        _add_conversation(db_path, f"clima {i}", "weather_query",
                          f"2026-08-0{i + 1} 08:15:00")
    engine = _engine(db_path)
    assert len(engine.detect_patterns(threshold=3)) == 1
    assert engine.detect_patterns(threshold=3) == []


def test_detect_patterns_umbral_no_alcanzado():
    db_path = _tmp_db()
    _add_conversation(db_path, "clima", "weather_query", "2026-08-01 08:15:00")
    _add_conversation(db_path, "clima", "weather_query", "2026-08-02 08:15:00")
    engine = _engine(db_path)
    assert engine.detect_patterns(threshold=3) == []


def test_detect_patterns_ignora_unknown_y_sin_datos():
    db_path = _tmp_db()
    for i in range(5):
        _add_conversation(db_path, f"x {i}", "unknown", f"2026-08-0{i + 1} 08:15:00")
    engine = _engine(db_path)
    assert engine.detect_patterns(threshold=3) == []
    assert _engine().detect_patterns() == []


# ==================== CRIPTOMONEDAS ====================

def test_monitor_crypto_detecta_movimiento():
    prices = iter([100.0, 105.0, 108.0])
    engine = _engine(fetch_price=lambda coin: next(prices))
    first = engine.monitor_crypto(coins=("bitcoin",))
    assert first == []  # sin precio previo no hay movimiento
    second = engine.monitor_crypto(coins=("bitcoin",))
    assert len(second) == 1
    assert second[0]["coin"] == "bitcoin"
    assert second[0]["change_pct"] == 5.0  # 100 → 105 = +5%


def test_monitor_crypto_sin_movimiento():
    engine = _engine(fetch_price=lambda coin: 100.0)
    engine.monitor_crypto(coins=("bitcoin",))
    assert engine.monitor_crypto(coins=("bitcoin",)) == []


def test_monitor_crypto_umbral_configurable():
    state = {"n": 0}

    def fetch(coin):
        state["n"] += 1
        return 100.0 if state["n"] == 1 else 101.0

    engine = _engine(fetch_price=fetch)
    engine.monitor_crypto(coins=("bitcoin",))
    # +1% desde 100 → supera umbral 0.5 pero no el default 3.
    assert engine.monitor_crypto(coins=("bitcoin",), threshold_pct=0.5)
    assert engine.monitor_crypto(coins=("bitcoin",)) == []


def test_monitor_crypto_deshabilitado():
    engine = _engine(fetch_price=lambda coin: 200.0, crypto_enabled=False)
    assert engine.monitor_crypto(coins=("bitcoin",)) == []


def test_monitor_crypto_fetch_falla_degrada():
    engine = _engine(fetch_price=lambda coin: None)
    assert engine.monitor_crypto(coins=("bitcoin",)) == []


def test_monitor_crypto_publica_evento():
    events = []

    class _Bus:
        def publish(self, event, priority=None):
            events.append(event.name)

    prices = iter([100.0, 110.0])
    engine = _engine(fetch_price=lambda coin: next(prices), event_bus=_Bus())
    engine.monitor_crypto(coins=("bitcoin",))
    engine.monitor_crypto(coins=("bitcoin",))
    assert "crypto_movement" in events


# ==================== CICLO DE VIDA ====================

def test_start_stop_hilo_daemon():
    engine = _engine(fetch_price=lambda coin: None)
    engine.start(intervals={"crypto": 1, "reminders": 1, "patterns": 1})
    time.sleep(2.5)
    assert engine.is_running()
    engine.stop()
    time.sleep(0.1)
    assert not engine.is_running()


def test_iso_parse_variantes():
    dt = _iso_parse("2026-08-12 08:15:00")
    assert dt is not None and dt.hour == 8
    assert _iso_parse("2026-08-12T08:15:00").minute == 15
    assert _iso_parse("garbage") is None
    assert _iso_parse(None) is None
