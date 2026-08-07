"""
agents/system.py - System Agent (SEMANA 5, FASE 1)

Control del sistema operativo (Windows):
- system_control: apagar / reiniciar / bloquear / suspender
- open_application: abrir apps web y locales
- take_screenshot: captura de pantalla (pyautogui)
- volume_control: subir/bajar/mutar volumen (pycaw opcional)
- open_folder: abrir carpeta en el Explorador
- empty_trash: vaciar la papelera de reciclaje
- lock_session: bloquear la sesión

Todas las acciones degradan elegante: si falta una librería o la acción
falla, se devuelve un resultado informativo sin lanzar excepciones.
"""

import os
import subprocess
import time
import webbrowser
from typing import Any, Dict, List, Optional

from agents.base import AgentBase

# Librerías opcionales (imports seguros)
try:
    import pyautogui
    _PYAUTOGUI_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin pyautogui
    pyautogui = None
    _PYAUTOGUI_AVAILABLE = False

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    _PYCAW_AVAILABLE = True
except Exception:  # pragma: no cover - entorno sin pycaw/comtypes
    AudioUtilities = None
    IAudioEndpointVolume = None
    _PYCAW_AVAILABLE = False


class SystemAgent(AgentBase):
    """Agente de control del sistema operativo."""

    _WEB_APPS: Dict[str, str] = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        "spotify": "https://open.spotify.com",
        "netflix": "https://www.netflix.com",
        "twitch": "https://www.twitch.tv",
        "twitter": "https://twitter.com",
        "x": "https://twitter.com",
        "wikipedia": "https://es.wikipedia.org",
        "maps": "https://maps.google.com",
        "chatgpt": "https://chat.openai.com",
        "whatsapp": "https://web.whatsapp.com",
    }

    _LOCAL_APPS: Dict[str, str] = {
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

    def __init__(
        self,
        agent_type: str = "system_agent",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=agent_type, agent_type=agent_type, config=config)
        self._handlers: Dict[str, Any] = {
            "system_control": self._control_system,
            "open_application": self._open_app,
            "take_screenshot": self._screenshot,
            "volume_control": self._volume,
            "open_folder": self._open_folder,
            "empty_trash": self._empty_trash,
            "lock_session": self._lock_session,
        }

    # ==================== PUNTO DE ENTRADA ====================

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un mensaje y ejecuta la acción del sistema.

        Args:
            message: Dict con "intent"/"name", "parameters"/"entities" y
                     "text"/"user_input" (opcional).

        Returns:
            {"status": ..., "data": {...}, "agent": "system_agent"}
        """
        if not isinstance(message, dict):
            return self._result("error", {"result": "Mensaje inválido"})

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
            data = self._smart_fallback(params, user_input, intent)
            return self._result("success", data)

        try:
            data = handler(params, user_input)
            return self._result("success", data)
        except Exception as e:
            self.record_error(f"process:{intent}", e)
            return self._result("error", {"intent": intent, "error": str(e)})

    def handle_event(self, event: Dict[str, Any]) -> None:
        """Reacciona a eventos del bus (por ahora solo registra)."""
        self.logger.debug(f"Evento recibido: {event}")

    # ==================== SISTEMA ====================

    def _control_system(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Apaga, reinicia, bloquea o suspende el equipo."""
        action = (params.get("action") or "").lower()
        text = user_input.lower()

        if (
            "reiniciar" in text or "reinicia" in text
            or action in ("reiniciar", "restart")
        ):
            os.system("shutdown /r /f /t 1")
            return {"action": "reiniciar", "result": "Reiniciando el sistema"}
        if (
            "bloquear" in text or "bloquea" in text
            or action in ("bloquear", "lock")
        ):
            os.system("rundll32 user32.dll,LockWorkStation")
            return {"action": "bloquear", "result": "Bloqueando el equipo"}
        if (
            "dormir" in text or "suspender" in text
            or action in ("dormir", "sleep", "suspender")
        ):
            os.system("rundll32 powrprof.dll,SetSuspendState 0,1,0")
            return {"action": "dormir", "result": "Poniendo el equipo en suspensión"}

        os.system("shutdown /s /f /t 1")
        return {"action": "apagar", "result": "Apagando el sistema"}

    def _lock_session(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Bloquea la sesión actual."""
        os.system("rundll32 user32.dll,LockWorkStation")
        return {"result": "Bloqueando la sesión"}

    # ==================== APLICACIONES Y CARPETAS ====================

    def _open_app(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Abre una aplicación web o local."""
        app = (params.get("application") or params.get("app_name") or "").strip()
        if not app:
            app = self._strip_query(
                user_input,
                ["abre el", "abre la", "abre", "abrir", "lanza", "ejecuta", "el", "la"],
            ).lower()
        if not app:
            return {"result": "¿Qué aplicación quieres que abra?"}

        if app in self._WEB_APPS:
            webbrowser.open(self._WEB_APPS[app])
            return {"result": f"Abriendo {app}", "mode": "web"}
        if app in self._LOCAL_APPS:
            os.startfile(self._LOCAL_APPS[app])
            return {"result": f"Abriendo {app}", "mode": "local"}

        try:
            os.startfile(app)
            return {"result": f"Abriendo {app}", "mode": "local"}
        except Exception:
            return {"result": f"No encontré la aplicación {app}"}

    def _open_folder(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Abre una carpeta en el Explorador."""
        folder = (
            params.get("path")
            or params.get("folder")
            or params.get("location")
            or ""
        ).strip()
        if not folder:
            folder = self._strip_query(
                user_input,
                ["abre la carpeta", "abre el folder", "abre", "carpeta",
                 "folder", "directorio", "mi"],
            )
            if not folder:
                return {"result": "¿Qué carpeta quieres abrir?"}

        folder = os.path.expanduser(folder)
        if os.path.isdir(folder):
            os.startfile(folder)
            return {"result": f"Abriendo la carpeta {folder}", "path": folder}
        return {"result": f"No encontré la carpeta {folder}"}

    # ==================== CAPTURA ====================

    def _screenshot(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Toma una captura de pantalla y la guarda."""
        if not _PYAUTOGUI_AVAILABLE:
            return {"result": "El módulo de captura no está disponible"}

        directory = (
            params.get("directory")
            or params.get("path")
            or os.path.join(os.path.expanduser("~"), "Pictures")
        )
        os.makedirs(directory, exist_ok=True)
        img = pyautogui.screenshot()
        file_name = f"captura_{int(time.time())}.png"
        path = os.path.join(directory, file_name)
        img.save(path)
        return {"result": f"Captura guardada en {path}", "path": path}

    # ==================== VOLUMEN (pycaw opcional) ====================

    def _volume(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Sube, baja o silencia el volumen del sistema."""
        direction = (params.get("direction") or "").lower()
        if not direction:
            direction = self._detect_volume_direction(user_input.lower())

        if not _PYCAW_AVAILABLE:
            return {
                "result": "Volumen: en desarrollo (instala pycaw para controlarlo)",
                "enabled": False,
            }

        ok = self._set_volume_pycaw(direction)
        if not ok:
            return {
                "result": "Volumen: en desarrollo (no se pudo ajustar)",
                "enabled": False,
            }
        return {"result": f"Volumen {direction}", "direction": direction, "enabled": True}

    @staticmethod
    def _detect_volume_direction(text: str) -> str:
        """Detecta la dirección del volumen a partir del texto."""
        if any(w in text for w in ("mutear", "silenciar", "mudo", "mute")):
            return "mute"
        if any(w in text for w in ("subir", "sube", "aumenta", "mas alto", "up")):
            return "up"
        if any(w in text for w in ("bajar", "baja", "menos", "mas bajo", "down")):
            return "down"
        return "up"

    def _set_volume_pycaw(self, direction: str) -> bool:
        """Ajusta el volumen vía pycaw. Devuelve True si tuvo éxito."""
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, 1, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)

            if direction == "mute":
                volume.SetMute(1, None)
                return True

            current = volume.GetMasterVolumeLevelScalar()
            step = 0.10
            delta = step if direction == "up" else -step
            new_value = max(0.0, min(1.0, current + delta))
            volume.SetMasterVolumeLevelScalar(new_value, None)
            return True
        except Exception as e:
            self.record_error("volume_pycaw", e)
            return False

    # ==================== PAPELERA ====================

    def _empty_trash(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Vacia la papelera de reciclaje."""
        try:
            subprocess.run(
                ["powershell", "-command",
                 "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
                timeout=30,
            )
            return {"result": "Papelera vaciada"}
        except Exception as e:
            self.record_error("empty_trash", e)
            return {"result": "No se pudo vaciar la papelera"}

    # ==================== PROCESOS ====================

    def list_processes(self, limit: int = 20) -> List[Dict[str, str]]:
        """Lista los procesos activos (tasklist)."""
        try:
            output = subprocess.run(
                ["tasklist"], capture_output=True, text=True, timeout=30
            ).stdout
        except Exception as e:
            self.record_error("list_processes", e)
            return []

        processes: List[Dict[str, str]] = []
        for line in output.splitlines()[3:]:
            parts = line.split()
            if len(parts) >= 2:
                processes.append({"name": parts[0], "pid": parts[1]})
            if len(processes) >= limit:
                break
        return processes

    def kill_process(self, name: str) -> Dict[str, Any]:
        """Termina un proceso por nombre (taskkill /F)."""
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", name],
                capture_output=True,
                timeout=30,
            )
            return {"result": f"Proceso {name} terminado"}
        except Exception as e:
            self.record_error("kill_process", e)
            return {"result": f"No se pudo terminar el proceso {name}"}

    # ==================== FALLBACK INTELIGENTE ====================

    def _smart_fallback(
        self, params: Dict[str, Any], user_input: str, intent: str
    ) -> Dict[str, Any]:
        """Atiende intenciones no mapeadas si el texto lo permite."""
        text = user_input.lower()
        if "proceso" in text or intent == "manage_processes":
            if any(w in text for w in ("mata", "matar", "kill", "termina", "cierra")):
                name = self._extract_process_name(text)
                if name:
                    return self.kill_process(name)
                return {"result": "¿Qué proceso quieres terminar?"}
            return {"result": "Procesos activos", "processes": self.list_processes()}
        return {"result": f"Acción '{intent}' en desarrollo"}

    @staticmethod
    def _extract_process_name(text: str) -> str:
        """Extrae el nombre del proceso tras la palabra clave."""
        for marker in ("mata a ", "matar a ", "kill ", "termina el proceso ",
                       "cierra el proceso ", "proceso "):
            if marker in text:
                rest = text.split(marker, 1)[-1].strip()
                if rest:
                    return rest.split()[0]
        return ""

    # ==================== UTILIDADES ====================

    @staticmethod
    def _strip_query(text: str, words) -> str:
        """Elimina palabras de relleno y devuelve la consulta limpia."""
        query = text
        for word in sorted(words, key=len, reverse=True):
            query = query.replace(word, " ")
        return " ".join(query.split()).strip(" ¿?¡!.,:-")

    @staticmethod
    def _result(status: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la respuesta estándar del agente."""
        return {"status": status, "data": data, "agent": "system_agent"}
