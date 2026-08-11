"""
agents/file.py - File Agent (SEMANA 6, FASE 1)

Gestión de archivos, notas, tareas y recordatorios:
- take_notes:    guarda una nota en SQLite (memory.py)
- create_task:   agrega una tarea con estado "pendiente"
- list_tasks:    lista las tareas con su estado (bonus)
- complete_task: marca una tarea como "completada" (bonus)
- read_file:     lee el contenido de un archivo en la carpeta de datos
- list_folder:   lista los archivos de la carpeta de datos
- reminder_set:  programa un recordatorio con fecha/hora

Almacenamiento:
- Notas, tareas y recordatorios viven en SQLite vía LongTermMemory
  (tabla `memories`, claves note::/task::/reminder::).
- Los archivos viven en la carpeta de datos de Jarvis (data_dir),
  con rutas seguras (sin path traversal).

Degradación elegante: si la base de datos falla, las notas se vuelven
volátiles; si un archivo no existe o el nombre es inválido, se responde
sin lanzar excepciones.
"""

import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base import AgentBase
from brain.memory import LongTermMemory

_NOTE_MARKERS = (
    "anota ", "apunta ", "escribe una nota", "guarda una nota",
    "take notes", "write a note", "make a note", "remember this",
)
_TASK_MARKERS = (
    "crea una tarea", "agrega una tarea", "agrega la tarea",
    "crear una tarea", "anota en mi to-do", "add a task", "create a task",
    "add to my list",
)
_REMINDER_MARKERS = (
    "recuérdame ", "recordatorio para", "alarma para", "recordatorio de",
    "remind me to", "set a reminder", "remind me in",
)


class FileAgent(AgentBase):
    """Agente de archivos, notas, tareas y recordatorios."""

    def __init__(
        self,
        agent_type: str = "file_agent",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=agent_type, agent_type=agent_type, config=config)
        cfg = config or {}
        self.data_dir: Path = Path(cfg.get("data_dir") or "data")
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # pragma: no cover - permisos
            pass
        db_path = cfg.get("db_path") or str(self.data_dir / "jarvis_memory.db")
        self._db_path = db_path
        try:
            self._store = LongTermMemory(db_path)
            self._db_available = True
        except Exception as e:  # pragma: no cover - defensivo
            self.record_error("init_store", e)
            self._store = None
            self._db_available = False
        self._handlers: Dict[str, Any] = {
            "take_notes": self._take_notes,
            "create_task": self._create_task,
            "list_tasks": self._list_tasks,
            "complete_task": self._complete_task,
            "read_file": self._read_file,
            "list_folder": self._list_folder,
            "reminder_set": self._reminder_set,
        }

    # ==================== PUNTO DE ENTRADA ====================

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un mensaje y resuelve la operación de archivos."""
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
        """Información del agente más sus capacidades."""
        info = super().get_info()
        info["capabilities"] = list(self._handlers.keys())
        info["data_dir"] = str(self.data_dir)
        info["db_available"] = self._db_available
        return info

    # ==================== NOTAS (SQLite) ====================

    def _take_notes(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Guarda una nota en la base de datos (tabla memories)."""
        note = (params.get("content") or params.get("note") or "").strip()
        if not note:
            note = self._after_phrase(user_input, _NOTE_MARKERS)
        if not note:
            return {"result": "¿Qué quieres que anote?"}

        key = f"note::{uuid.uuid4().hex[:8]}"
        saved = self._save_entry(
            key,
            {"content": note},
            {"type": "note"},
            "normal",
        )
        if not saved:
            return {"result": "No pude guardar la nota (almacenamiento no disponible).",
                    "note": note, "saved": False}
        return {"result": f"Nota guardada: {note}", "note": note, "saved": True,
                "key": key}

    # ==================== TAREAS (SQLite, con estado) ====================

    def _create_task(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Agrega una tarea con estado 'pendiente'."""
        task = (
            params.get("task_description")
            or params.get("task")
            or params.get("content")
            or ""
        ).strip()
        if not task:
            task = self._after_phrase(user_input, _TASK_MARKERS)
        if not task:
            return {"result": "¿Qué tarea quieres agregar?"}

        key = f"task::{uuid.uuid4().hex[:8]}"
        saved = self._save_entry(
            key,
            {"description": task},
            {"type": "task", "status": "pendiente"},
            "normal",
        )
        if not saved:
            return {"result": "No pude guardar la tarea (almacenamiento no disponible).",
                    "task": task, "saved": False}
        return {"result": f"Tarea agregada: {task} (pendiente)", "task": task,
                "status": "pendiente", "saved": True, "key": key}

    def _list_tasks(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Lista las tareas con su estado (pendiente/completada)."""
        tasks = self._entries_by_type("task")
        if not tasks:
            return {"result": "No tienes tareas.", "tasks": [], "count": 0}

        lines = [
            f"- [{'x' if t['metadata'].get('status') == 'completada' else ' '}] "
            f"{t['value'].get('description', '')}"
            for t in tasks
        ]
        return {
            "result": "Tus tareas:\n" + "\n".join(lines),
            "tasks": tasks,
            "count": len(tasks),
        }

    def _complete_task(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Marca una tarea como completada (por texto o por key)."""
        query = (params.get("task") or params.get("task_description") or "").strip()
        key = params.get("key") or ""
        if not query and key:
            query = key
        if not query:
            query = self._after_phrase(user_input, ("completa ", "marca como completada"))

        tasks = self._entries_by_type("task")
        if not tasks:
            return {"result": "No tienes tareas para completar."}

        target = None
        if key:
            target = next((t for t in tasks if t["key"] == key), None)
        if target is None and query:
            low_query = query.lower()
            target = next(
                (t for t in tasks if low_query in t["value"].get("description", "").lower()),
                None,
            )
        if target is None:
            return {"result": "No encontré esa tarea."}

        metadata = dict(target["metadata"])
        metadata["status"] = "completada"
        saved = self._save_entry(
            target["key"], target["value"], metadata, "normal"
        )
        if not saved:
            return {"result": "No pude actualizar la tarea (almacenamiento no disponible)."}
        description = target["value"].get("description", "")
        return {"result": f"Tarea completada: {description}",
                "task": description, "status": "completada"}

    # ==================== RECORDATORIOS (SQLite, fecha/hora) ====================

    def _reminder_set(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Programa un recordatorio con fecha/hora."""
        task = (params.get("task") or params.get("content") or "").strip()
        if not task:
            task = self._after_phrase(user_input, _REMINDER_MARKERS)
        if not task:
            return {"result": "¿Qué quieres que te recuerde?"}

        when = self._parse_reminder_time(params, user_input)
        if when is None:
            when = datetime.now() + timedelta(hours=1)
            source = "default"
        else:
            source = "parsed"

        key = f"reminder::{uuid.uuid4().hex[:8]}"
        saved = self._save_entry(
            key,
            {"message": task, "when": when.isoformat()},
            {"type": "reminder", "status": "pendiente"},
            "high",
        )
        if not saved:
            return {"result": "No pude guardar el recordatorio (almacenamiento no disponible).",
                    "saved": False}
        return {
            "result": f"Recordatorio programado para {when.strftime('%Y-%m-%d %H:%M')}: {task}",
            "task": task,
            "when": when.isoformat(),
            "saved": True,
            "source": source,
        }

    def _parse_reminder_time(
        self, params: Dict[str, Any], user_input: str
    ) -> Optional[datetime]:
        """Extrae una fecha/hora de los parámetros o del texto."""
        raw = (params.get("time") or params.get("when") or "").strip()
        text = user_input or raw

        # HH:MM o "a las HH:MM"
        m = re.search(r"(?:a las |al |@ )?(\d{1,2})[:.](\d{2})", text)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                now = datetime.now()
                when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if when <= now:
                    when += timedelta(days=1)
                return when

        # "en N minutos/horas"
        m = re.search(r"en\s+(\d+)\s*(minuto|hora)", text, re.IGNORECASE)
        if m:
            amount = int(m.group(1))
            unit = m.group(2).lower()
            delta = timedelta(minutes=amount) if "minuto" in unit else timedelta(hours=amount)
            return datetime.now() + delta

        # "mañana a las HH" → mañana a esa hora
        m = re.search(r"mañana(?:\s+a las\s+(\d{1,2}))?", text, re.IGNORECASE)
        if m:
            tomorrow = datetime.now() + timedelta(days=1)
            hour = int(m.group(1)) if m.group(1) else 9
            return tomorrow.replace(hour=min(hour, 23), minute=0, second=0, microsecond=0)

        return None

    # ==================== ARCHIVOS (data_dir) ====================

    def _read_file(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Lee el contenido de un archivo dentro de data_dir."""
        filename = (params.get("filename") or params.get("file_name") or params.get("file") or "").strip()
        if not filename:
            filename = self._after_phrase(user_input, ("lee el archivo", "lee ", "abre "))
        if not filename:
            return {"result": "¿Qué archivo quieres que lea?"}

        path = self._safe_path(filename)
        if path is None:
            return {"result": f"Nombre de archivo inválido: {filename}"}
        if not path.is_file():
            return {"result": f"No encontré el archivo '{filename}'."}

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # pragma: no cover - permisos/IO
            self.record_error("read_file", e)
            return {"result": f"No pude leer el archivo '{filename}'."}

        if not content.strip():
            content = "(archivo vacío)"
        return {"result": content, "filename": filename, "bytes": len(content.encode("utf-8"))}

    def _list_folder(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Lista los archivos de data_dir (archivos de Jarvis)."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            files = sorted(
                p.name for p in self.data_dir.iterdir()
                if p.is_file() and not p.name.endswith(".db")
            )
        except Exception as e:  # pragma: no cover - permisos/IO
            self.record_error("list_folder", e)
            return {"result": "No pude listar la carpeta de datos."}

        if not files:
            return {"result": "La carpeta de datos está vacía.", "files": []}
        return {"result": "Archivos en la carpeta de datos:\n" + "\n".join(f"- {f}" for f in files),
                "files": files}

    def _safe_path(self, filename: str) -> Optional[Path]:
        """Resuelve un nombre de archivo dentro de data_dir (sin path traversal)."""
        name = filename.replace("\\", "/").strip()
        if not name or name in (".", ".."):
            return None
        try:
            base = self.data_dir.resolve()
            candidate = (self.data_dir / name).resolve()
            if not str(candidate).startswith(str(base)):
                return None
            return candidate
        except Exception:  # pragma: no cover - defensivo
            return None

    # ==================== ACCESO A SQLite (LongTermMemory) ====================

    def _save_entry(
        self,
        key: str,
        value: Dict[str, Any],
        metadata: Dict[str, Any],
        importance: str,
    ) -> bool:
        """Guarda una entrada en la tabla memories de SQLite."""
        if not self._db_available or self._store is None:
            return False
        try:
            self._store._save_sync(key, value, metadata, importance)
            return True
        except Exception as e:
            self.record_error("save_entry", e)
            return False

    def _entries_by_type(self, item_type: str) -> List[Dict[str, Any]]:
        """Devuelve todas las entradas de un tipo (note/task/reminder)."""
        if not self._db_available or self._store is None:
            return []
        try:
            rows = self._store._search_memories_sync("", limit=500)
        except Exception as e:
            self.record_error("entries_by_type", e)
            return []
        result = []
        for row in rows:
            metadata = row.get("metadata") or {}
            if metadata.get("type") == item_type:
                result.append(row)
        return result

    # ==================== UTILIDADES ====================

    @staticmethod
    def _after_phrase(text: str, markers: tuple) -> str:
        """Devuelve el texto tras la primera frase encontrada (si existe)."""
        if not text:
            return ""
        low = text.lower()
        for marker in sorted(markers, key=len, reverse=True):
            idx = low.find(marker)
            if idx >= 0:
                rest = text[idx + len(marker):]
                return rest.strip(" ¿?¡!.,:-;\"'")
        return text.strip(" ¿?¡!.,:-;\"'")

    @staticmethod
    def _result(status: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la respuesta estándar del agente."""
        return {"status": status, "data": data, "agent": "file_agent"}
