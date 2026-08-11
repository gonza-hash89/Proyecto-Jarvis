"""
agents/voice.py - Voice Agent (SEMANA 6, FASE 2)

Síntesis y reconocimiento de voz con degradación elegante:
- speak:  edge-tts (voz neural, es-ES-AlvaroNeural) → pyttsx3 (offline) → texto
- listen: speech_recognition con calibración automática de ruido ambiente y
          detección de silencio mejorada (energy_threshold dinámico + pausas)

Todas las librerías (edge_tts, pyttsx3, pygame, speech_recognition) son
opcionales: si faltan, Jarvis degrada sin lanzar excepciones.

Declaración de honestidad: la voz es síntesis/reconocimiento, no conciencia;
el agente solo convierte texto↔audio de forma verificable y testeable.
"""

import asyncio
import os
import tempfile
import time
import uuid
from typing import Any, Dict, Optional

from agents.base import AgentBase

# Librerías opcionales (imports seguros)
try:
    import edge_tts
    _EDGE_TTS_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin edge-tts
    edge_tts = None
    _EDGE_TTS_AVAILABLE = False

try:
    import pyttsx3
    _VOICE_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin pyttsx3
    pyttsx3 = None
    _VOICE_AVAILABLE = False

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin pygame
    pygame = None
    _PYGAME_AVAILABLE = False

try:
    import speech_recognition as sr
    _SR_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin speech_recognition
    sr = None
    _SR_AVAILABLE = False


class VoiceAgent(AgentBase):
    """Agente de voz: síntesis neural con fallback offline y escucha calibrada."""

    def __init__(
        self,
        agent_type: str = "voice_agent",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=agent_type, agent_type=agent_type, config=config)
        cfg = config or {}
        self.engine_choice: str = cfg.get("engine", "edge")
        self.voice: str = cfg.get("voice", "es-ES-AlvaroNeural")
        self.rate: int = int(cfg.get("rate", 150))
        self.volume: float = float(cfg.get("volume", 1.0))
        self.voice_id: int = int(cfg.get("voice_id", 1))
        self.language: str = cfg.get("language", "es-ES")
        self.timeout: int = int(cfg.get("timeout", 5))
        self.pause_threshold: float = float(cfg.get("pause_threshold", 0.8))
        self.calibration_duration: float = float(cfg.get("calibration_duration", 0.5))
        self._tts_engine: Optional[Any] = None
        self._handlers: Dict[str, Any] = {
            "speak_text": self._speak_handler,
            "listen_voice": self._listen_handler,
            "calibrate_mic": self._calibrate_handler,
        }
        self._init_tts()

    # ==================== INICIALIZACIÓN ====================

    def _init_tts(self) -> None:
        """Inicializa el motor de síntesis según disponibilidad.

        Prioridad: edge-tts (neural) → pyttsx3 (offline) → texto.
        """
        if self.engine_choice == "edge" and _EDGE_TTS_AVAILABLE:
            if _PYGAME_AVAILABLE:
                try:
                    pygame.mixer.init()
                except Exception as e:  # pragma: no cover - audio de sistema
                    self.logger.warning(f"pygame.mixer falló: {e}")
                self._engine_name = "edge"
                self.logger.info(f"VoiceAgent listo (edge-tts, voz={self.voice})")
                return

        if _VOICE_AVAILABLE:
            try:
                self._tts_engine = pyttsx3.init()
                voices = self._tts_engine.getProperty("voices")
                if voices and 0 <= self.voice_id < len(voices):
                    self._tts_engine.setProperty("voice", voices[self.voice_id].id)
                self._tts_engine.setProperty("rate", self.rate)
                self._tts_engine.setProperty("volume", self.volume)
                self._engine_name = "pyttsx3"
                self.logger.info(f"VoiceAgent listo (pyttsx3, rate={self.rate})")
                return
            except Exception as e:  # pragma: no cover - motor roto
                self._tts_engine = None
                self.logger.warning(f"pyttsx3 falló: {e}")

        self._engine_name = "text"
        self.logger.warning("Sin motor de voz. VoiceAgent en modo texto.")

    # ==================== PUNTO DE ENTRADA ====================

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un mensaje de voz (sintetizar, escuchar o calibrar)."""
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
        """Información del agente más sus capacidades y dependencias."""
        info = super().get_info()
        info["capabilities"] = list(self._handlers.keys())
        info["engine"] = self._engine_name
        info["dependencies"] = {
            "edge_tts": _EDGE_TTS_AVAILABLE,
            "pyttsx3": _VOICE_AVAILABLE,
            "pygame": _PYGAME_AVAILABLE,
            "speech_recognition": _SR_AVAILABLE,
        }
        return info

    # ==================== SÍNTESIS (speak) ====================

    def speak(self, text: str) -> Dict[str, Any]:
        """Sintetiza un texto: edge-tts → pyttsx3 → modo texto.

        Returns:
            {"result": texto, "mode": "edge"|"pyttsx3"|"text", "spoken": bool}
        """
        if not text or not str(text).strip():
            return {"result": "", "mode": "text", "spoken": False}

        if self.engine_choice == "edge" and _EDGE_TTS_AVAILABLE and _PYGAME_AVAILABLE:
            if self._speak_edge(str(text)):
                return {"result": str(text), "mode": "edge", "spoken": True}

        if self._tts_engine is not None:
            if self._speak_pyttsx3(str(text)):
                return {"result": str(text), "mode": "pyttsx3", "spoken": True}

        return {"result": str(text), "mode": "text", "spoken": False}

    def _speak_edge(self, text: str) -> bool:
        """Genera audio neural con edge-tts y lo reproduce con pygame."""
        try:
            mp3_path = os.path.join(
                tempfile.gettempdir(), f"jarvis_voice_{uuid.uuid4().hex[:8]}.mp3"
            )
            asyncio.run(edge_tts.Communicate(text, self.voice).save(mp3_path))
            try:
                if _PYGAME_AVAILABLE and pygame.mixer.get_init() is not None:
                    pygame.mixer.music.load(mp3_path)
                    pygame.mixer.music.set_volume(self.volume)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        time.sleep(0.1)
                    pygame.mixer.music.unload()
            finally:
                try:
                    os.remove(mp3_path)
                except OSError:  # pragma: no cover - archivo ya borrado
                    pass
            return True
        except Exception as e:
            self.record_error("speak_edge", e)
            return False

    def _speak_pyttsx3(self, text: str) -> bool:
        """Habla con pyttsx3 (fallback offline)."""
        try:
            self._tts_engine.say(text)
            self._tts_engine.runAndWait()
            return True
        except Exception as e:
            self.record_error("speak_pyttsx3", e)
            return False

    # ==================== ESCUCHA (listen) ====================

    def listen(self, timeout: Optional[int] = None) -> Optional[str]:
        """Escucha y reconoce voz con calibración de ruido y silencio mejorado.

        Returns:
            El texto reconocido (minúsculas), o None si no se entendió.
        """
        if not _SR_AVAILABLE:
            return None

        recognizer = sr.Recognizer()
        recognizer.pause_threshold = self.pause_threshold
        recognizer.dynamic_energy_threshold = True
        recognizer.dynamic_energy_adjustment_damping = 0.15
        recognizer.dynamic_energy_ratio = 1.5

        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(
                    source, duration=self.calibration_duration
                )
                try:
                    audio = recognizer.listen(
                        source,
                        timeout=timeout or self.timeout,
                        phrase_time_limit=self.timeout + 5,
                    )
                except sr.WaitTimeoutError:
                    self.logger.info("Tiempo de escucha agotado (silencio)")
                    return None

            return self._recognize(recognizer, audio)
        except sr.UnknownValueError:
            self.logger.info("Voz no entendida")
            return None
        except sr.RequestError:
            self.logger.warning("Servicio de reconocimiento no disponible")
            return None
        except Exception as e:  # pragma: no cover - micrófono ausente
            self.record_error("listen", e)
            return None

    def _recognize(self, recognizer: Any, audio: Any) -> Optional[str]:
        """Convierte audio a texto vía Google (o None si no se entiende)."""
        try:
            text = recognizer.recognize_google(audio, language=self.language).lower().strip()
            return text or None
        except (sr.UnknownValueError, sr.RequestError):
            return None

    # ==================== CALIBRACIÓN ====================

    def calibrate_mic(self, duration: Optional[float] = None) -> Dict[str, Any]:
        """Calibra el ruido ambiente y devuelve el umbral de energía detectado."""
        if not _SR_AVAILABLE:
            return {"energy_threshold": None, "calibrated": False, "reason": "sr_no_disponible"}

        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(
                    source, duration=duration or self.calibration_duration
                )
            return {
                "energy_threshold": recognizer.energy_threshold,
                "calibrated": True,
                "duration": duration or self.calibration_duration,
            }
        except Exception as e:  # pragma: no cover - micrófono ausente
            self.record_error("calibrate_mic", e)
            return {"energy_threshold": None, "calibrated": False, "reason": str(e)}

    # ==================== HANDLERS (interfaz de agente) ====================

    def _speak_handler(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        text = params.get("text") or user_input or ""
        return self.speak(text)

    def _listen_handler(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        text = self.listen()
        if text is None:
            return {"result": "No entendí lo que dijiste.", "transcript": None}
        return {"result": text, "transcript": text}

    def _calibrate_handler(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        duration = params.get("duration")
        calibration = self.calibrate_mic(float(duration) if duration else None)
        return {"result": f"Umbral de ruido: {calibration['energy_threshold']}",
                **calibration}

    # ==================== UTILIDADES ====================

    @staticmethod
    def _result(status: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la respuesta estándar del agente."""
        return {"status": status, "data": data, "agent": "voice_agent"}
