"""
brain/proactive.py - Motor proactivo de Jarvis (SEMANA 8, FASE 2)

Jarvis deja de ser puramente reactivo: en segundo plano (hilo daemon)
puede:

1. check_reminders():  avisar cuando llega la hora de un recordatorio.
2. detect_patterns():  descubrir hábitos del usuario analizando el
                       historial de conversaciones (intención + franja horaria).
3. monitor_crypto():  vigilar el precio de criptos y avisar ante movimientos
                       bruscos (sin API externa obligatoria: degrada silencioso).

DECLARACION DE HONESTIDAD:
Nada de esto es "iniciativa" mágica: son reglas deterministas y
observables que corren en un hilo separado y publican eventos en el bus.
Si no hay datos o red, simplemente no hace nada (degradación elegante).
"""

import threading
import time
from collections import Counter
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from brain.memory import LongTermMemory

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = _requests is not None
except ImportError:  # pragma: no cover - entorno sin requests
    _requests = None
    _REQUESTS_AVAILABLE = False


def _iso_parse(raw: str) -> Optional[datetime]:
    """Parsea un timestamp ISO o 'YYYY-MM-DD HH:MM:SS' (SQLite)."""
    if not raw:
        return None
    text = str(raw).strip()
    if "T" not in text and len(text) >= 19:
        text = text[:19].replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class ProactiveEngine:
    """Motor proactivo con ciclo en hilo daemon.

    Los métodos de detección (check_reminders / detect_patterns /
    monitor_crypto) son públicos y síncronos: fáciles de testear sin hilo.
    start()/stop() solo controlan el bucle que los invoca cada intervalo.
    """

    DEFAULT_INTERVALS = {
        "reminders": 30,
        "patterns": 3600,
        "crypto": 600,
    }

    def __init__(
        self,
        config: Optional[Any] = None,
        logger: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        db_path: str = "data/jarvis_memory.db",
        fetch_price: Optional[Callable[[str], Optional[float]]] = None,
        crypto_enabled: bool = True,
    ) -> None:
        self._config = config
        self._logger = logger
        self._event_bus = event_bus
        self.db_path = db_path
        self._store: Optional[LongTermMemory] = None
        self._fetch_price = fetch_price or self._fetch_price_online
        self._crypto_enabled = crypto_enabled
        self._crypto_threshold_pct = 3.0
        self._last_prices: Dict[str, float] = {}
        self._reported_patterns: set = set()

        # Callbacks opcionales (p.ej. el orquestador los conecta a speak()).
        self.on_reminder: Optional[Callable[[str], None]] = None
        self.on_pattern: Optional[Callable[[str], None]] = None
        self.on_crypto: Optional[Callable[[str], None]] = None

        # Hilo
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._intervals: Dict[str, int] = dict(self.DEFAULT_INTERVALS)

        self._init_store()

    # ==================== ALMACÉN ====================

    def _init_store(self) -> None:
        """Crea/abre la memoria persistente (SQLite) con degradación."""
        try:
            self._store = LongTermMemory(self.db_path)
        except Exception as e:
            self._log(f"No se pudo abrir la memoria: {e}")
            self._store = None

    def _log(self, message: str, level: str = "info") -> None:
        logger = self._logger
        if logger is None:
            return
        fn = getattr(logger, level, None) or getattr(logger, "info", None)
        try:
            fn(f"[proactive] {message}")
        except Exception:
            pass

    # ==================== CICLO DE VIDA ====================

    def start(self, intervals: Optional[Dict[str, int]] = None) -> None:
        """Arranca el hilo daemon que invoca las detecciones periódicas."""
        if intervals:
            self._intervals.update(intervals)
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="jarvis-proactive"
        )
        self._thread.start()
        self._log("ProactiveEngine iniciado")

    def stop(self) -> None:
        """Detiene el bucle del hilo proactivo."""
        self._running = False
        self._log("ProactiveEngine detenido")

    def is_running(self) -> bool:
        """True si el hilo proactivo está activo."""
        return self._running and self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        """Bucle principal: ejecuta cada tarea según su intervalo."""
        last: Dict[str, float] = {}
        while self._running:
            now = time.time()
            for task, interval in self._intervals.items():
                if now - last.get(task, 0) < interval:
                    continue
                last[task] = now
                try:
                    self._run_task(task)
                except Exception as e:
                    self._log(f"Tarea '{task}' falló: {e}", "warning")
            time.sleep(1)

    def _run_task(self, task: str) -> None:
        """Ejecuta una tarea proactiva por su nombre."""
        if task == "reminders":
            self.check_reminders()
        elif task == "patterns":
            self.detect_patterns()
        elif task == "crypto":
            self.monitor_crypto()

    # ==================== RECORDATORIOS ====================

    def check_reminders(self) -> List[Dict[str, Any]]:
        """Busca recordatorios vencidos y los notifica una sola vez.

        Returns:
            Lista de recordatorios vencidos (mensaje + hora).
        """
        if self._store is None:
            return []
        now = datetime.now()
        due: List[Dict[str, Any]] = []
        try:
            rows = self._store._search_memories_sync("", limit=500)
        except Exception as e:
            self._log(f"Error leyendo recordatorios: {e}", "warning")
            return []

        for row in rows:
            metadata = row.get("metadata") or {}
            if metadata.get("type") != "reminder":
                continue
            if metadata.get("status") == "notificado":
                continue
            value = row.get("value") or {}
            when = _iso_parse(value.get("when"))
            if when is None or when > now:
                continue
            message = value.get("message") or "Tienes un recordatorio"
            due.append({"key": row.get("key"), "message": message, "when": when.isoformat()})
            # Marcar como notificado para no repetir el aviso.
            try:
                self._store._save_sync(
                    row.get("key"),
                    value,
                    {**metadata, "status": "notificado"},
                    "high",
                )
            except Exception as e:
                self._log(f"No se pudo marcar recordatorio: {e}", "warning")

        if due:
            text = self._format_reminders(due)
            self._publish("reminder_due", {"reminders": due, "text": text})
            if self.on_reminder:
                try:
                    self.on_reminder(text)
                except Exception as e:
                    self._log(f"Callback de recordatorio falló: {e}", "warning")
            self._log(f"{len(due)} recordatorio(s) vencido(s) notificado(s)")
        return due

    @staticmethod
    def _format_reminders(due: List[Dict[str, Any]]) -> str:
        """Convierte los recordatorios vencidos en texto hablable."""
        if len(due) == 1:
            return f"Te recuerdo: {due[0]['message']}"
        items = "; ".join(d["message"] for d in due)
        return f"Tienes {len(due)} recordatorios: {items}."

    # ==================== PATRONES ====================

    def detect_patterns(self, threshold: int = 3) -> List[Dict[str, Any]]:
        """Detecta hábitos (intención repetida en la misma franja horaria).

        Returns:
            Lista de patrones NUEVOS (no reportados antes en esta sesión).
        """
        if self._store is None:
            return []
        try:
            rows = self._store._search_conversations_sync("", limit=300)
        except Exception as e:
            self._log(f"Error leyendo conversaciones: {e}", "warning")
            return []

        counts: Counter = Counter()
        for row in rows:
            intent = row.get("intent") or ""
            if intent in ("", "unknown", "exit"):
                continue
            hour = self._hour_of(row.get("timestamp"))
            if hour is None:
                continue
            slot = hour - (hour % 2)
            counts[(intent, slot)] += 1

        patterns: List[Dict[str, Any]] = []
        for (intent, slot), count in sorted(counts.items()):
            if count < threshold:
                continue
            if (intent, slot) in self._reported_patterns:
                continue
            self._reported_patterns.add((intent, slot))
            patterns.append({"intent": intent, "slot": slot, "count": count})

        if patterns:
            text = self._format_patterns(patterns)
            self._publish("pattern_detected", {"patterns": patterns, "text": text})
            if self.on_pattern:
                try:
                    self.on_pattern(text)
                except Exception as e:
                    self._log(f"Callback de patrón falló: {e}", "warning")
            self._log(f"{len(patterns)} patrón(es) detectado(s)")
        return patterns

    @staticmethod
    def _hour_of(timestamp: Any) -> Optional[int]:
        """Extrae la hora (0-23) de un timestamp SQLite."""
        dt = _iso_parse(timestamp)
        return dt.hour if dt is not None else None

    @staticmethod
    def _slot_label(slot: int) -> str:
        """Etiqueta de franja horaria: '08:00-09:59' para slot 8."""
        return f"{slot:02d}:00-{slot + 1:02d}:59"

    def _format_patterns(self, patterns: List[Dict[str, Any]]) -> str:
        lines = ["He notado un hábito tuyo:"]
        for p in patterns:
            lines.append(
                f"- Sueles pedir '{p['intent']}' entre las "
                f"{self._slot_label(p['slot'])} ({p['count']} veces)"
            )
        return "\n".join(lines)

    # ==================== CRIPTOMONEDAS ====================

    def monitor_crypto(
        self,
        coins: tuple = ("bitcoin", "ethereum"),
        threshold_pct: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Vigila precios y reporta movimientos >= umbral (default 3%).

        Returns:
            Lista de movimientos detectados (coin, price, change_pct).
        """
        if not self._crypto_enabled:
            return []
        threshold = threshold_pct if threshold_pct is not None else self._crypto_threshold_pct
        movements: List[Dict[str, Any]] = []
        for coin in coins:
            price = self._fetch_price(coin)
            if price is None:
                continue
            previous = self._last_prices.get(coin)
            if previous is not None and previous > 0:
                change_pct = (price - previous) / previous * 100
                if abs(change_pct) >= threshold:
                    movements.append({
                        "coin": coin,
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 2),
                    })
            self._last_prices[coin] = price

        if movements:
            text = self._format_movements(movements)
            self._publish("crypto_movement", {"movements": movements, "text": text})
            if self.on_crypto:
                try:
                    self.on_crypto(text)
                except Exception as e:
                    self._log(f"Callback de cripto falló: {e}", "warning")
            self._log(f"{len(movements)} movimiento(s) cripto detectado(s)")
        return movements

    @staticmethod
    def _fetch_price_online(coin_id: str) -> Optional[float]:
        """Precio de una cripto vía CoinGecko (None si no hay red)."""
        if not _REQUESTS_AVAILABLE:
            return None
        try:
            resp = _requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd"},
                timeout=10,
            )
            data = resp.json()
            return data.get(coin_id, {}).get("usd")
        except Exception:  # noqa: BLE001 - degradación silenciosa
            return None

    @staticmethod
    def _format_movements(movements: List[Dict[str, Any]]) -> str:
        lines = ["Movimientos de criptomonedas:"]
        for m in movements:
            direction = "subió" if m["change_pct"] >= 0 else "bajó"
            lines.append(
                f"- {m['coin']}: {m['price']:.2f} USD "
                f"({direction} {abs(m['change_pct']):.2f}%)"
            )
        return "\n".join(lines)

    # ==================== EVENTOS ====================

    def _publish(self, event_name: str, payload: Dict[str, Any]) -> None:
        """Publica un evento en el bus si está disponible (nombres libres)."""
        if self._event_bus is None:
            return
        try:
            from orchestrator.events import make_event

            self._event_bus.publish(make_event(event_name, payload))
        except Exception as e:
            self._log(f"No se pudo publicar '{event_name}': {e}", "warning")
