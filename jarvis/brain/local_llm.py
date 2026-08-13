"""
brain/local_llm.py - LLM local opcional (SEMANA 8, FASE 4)

Jarvis puede generar texto "por sí mismo" usando una cadena de proveedores
con degradación elegante:

1. Ollama (local, privado, sin nube):  http://localhost:11434/api/generate
2. Gemini (nube, opcional):            requiere GEMINI_API_KEY + librería
3. Plantillas (último recurso):        respuesta determinista y honesta

La regla es: el PRIMER proveedor que devuelva texto gana. Si ninguno lo
hace, generate() devuelve {"text": None}. Nunca lanza excepciones hacia
arriba: degrada silenciosamente.

DECLARACION DE HONESTIDAD:
Si no hay Ollama ni Gemini, Jarvis NO pretende "pensar": usa plantillas.
El wrapper es 100% inyectable y testeable sin red (providers=fakes).
"""

import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = _requests is not None
except ImportError:  # pragma: no cover - entorno sin requests
    _requests = None
    _REQUESTS_AVAILABLE = False

try:
    import google.generativeai as _genai
    _GENAI_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin librería
    _genai = None
    _GENAI_AVAILABLE = False

# Modelos de Gemini probados en orden (por disponibilidad).
_GEMINI_MODELS = ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro")

OLLAMA_BASE_URL = "http://localhost:11434"


class LocalLLM:
    """Wrapper de LLM local con cadena de fallback Ollama → Gemini → plantillas.

    Args:
        model:      Modelo de Ollama (ej: "llama3.2", "mistral").
        api_key:    Key de Gemini (por defecto: variable GEMINI_API_KEY).
        base_url:   URL de la API local de Ollama.
        timeout:    Segundos de espera por proveedor.
        providers:  Lista de (nombre, callable(prompt, system)->Optional[str]).
                    Si se omite, usa la cadena por defecto.
    """

    def __init__(
        self,
        model: str = "llama3.2",
        api_key: Optional[str] = None,
        base_url: str = OLLAMA_BASE_URL,
        timeout: float = 8.0,
        providers: Optional[List[Tuple[str, Callable[[str, Optional[str]], Optional[str]]]]] = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._gemini_model: Optional[Any] = None
        self._last_provider: Optional[str] = None
        self._calls = 0

        if providers is not None:
            self._providers = list(providers)
        else:
            self._providers: List[Tuple[str, Callable[[str, Optional[str]], Optional[str]]]] = [
                ("ollama", self._ollama_chat),
                ("gemini", self._gemini_chat),
                ("templates", self._templates_chat),
            ]

    # ==================== API PÚBLICA ====================

    def generate(
        self, prompt: str, system: Optional[str] = None
    ) -> Dict[str, Any]:
        """Genera texto con el primer proveedor disponible.

        Returns:
            {"text": str, "provider": str} o {"text": None, "provider": None}.
        """
        self._calls += 1
        for name, provider in self._providers:
            try:
                text = provider(prompt, system)
            except Exception:  # noqa: BLE001 - degradación elegante
                text = None
            if text and text.strip():
                self._last_provider = name
                return {"text": text.strip(), "provider": name}
        self._last_provider = None
        return {"text": None, "provider": None}

    def generate_text(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        """Igual que generate() pero devuelve solo el texto (o None)."""
        result = self.generate(prompt, system=system)
        return result.get("text")

    def available(self) -> bool:
        """True si algún proveedor externo podría responder ahora.

        Hace un ping corto a Ollama y verifica la key de Gemini. Las
        plantillas siempre existen, pero NO cuentan como "LLM real".
        """
        if self._ollama_reachable():
            return True
        return bool(_GENAI_AVAILABLE and self._api_key)

    def get_last_provider(self) -> Optional[str]:
        """Proveedor que respondió en la última llamada."""
        return self._last_provider

    def get_status(self) -> Dict[str, Any]:
        """Estado del wrapper (para autoconciencia N4 y logs)."""
        return {
            "model": self.model,
            "ollama": self._ollama_reachable(),
            "gemini": bool(_GENAI_AVAILABLE and self._api_key),
            "providers": [name for name, _ in self._providers],
            "last_provider": self._last_provider,
            "calls": self._calls,
        }

    # ==================== OLLAMA ====================

    def _ollama_reachable(self) -> bool:
        """Ping corto a la API de Ollama (sin bloquear mucho tiempo)."""
        if not _REQUESTS_AVAILABLE:
            return False
        try:
            resp = _requests.get(f"{self.base_url}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def _ollama_chat(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        """Llama al endpoint /api/generate de Ollama (stream off)."""
        if not _REQUESTS_AVAILABLE:
            return None
        body: Dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            body["system"] = system
        resp = _requests.post(
            f"{self.base_url}/api/generate", json=body, timeout=self.timeout
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return (data.get("response") or "").strip() or None

    # ==================== GEMINI ====================

    def _gemini_enabled(self) -> bool:
        return bool(_GENAI_AVAILABLE and self._api_key)

    def _gemini_chat(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        """Consulta a Gemini (nube) si hay key y librería."""
        if not self._gemini_enabled():
            return None
        if self._gemini_model is None:
            _genai.configure(api_key=self._api_key)
            self._gemini_model = self._create_gemini_model()
            if self._gemini_model is None:
                return None
        try:
            response = self._gemini_model.generate_content(prompt)
            return (getattr(response, "text", "") or "").strip() or None
        except Exception:  # noqa: BLE001 - degradación
            return None

    def _create_gemini_model(self) -> Optional[Any]:
        """Crea el modelo Gemini probando nombres estables."""
        for name in _GEMINI_MODELS:
            try:
                return _genai.GenerativeModel(name)
            except Exception:  # pragma: no cover - nombre no disponible
                continue
        return None

    # ==================== PLANTILLAS (último recurso) ====================

    @staticmethod
    def _templates_chat(prompt: str, system: Optional[str] = None) -> str:
        """Respuesta determinista cuando no hay ningún LLM disponible."""
        short = " ".join((prompt or "").split())
        if len(short) > 160:
            short = short[:157] + "..."
        if system:
            return (
                f"(Plantillas) {system} | No hay LLM local ni nube activos. "
                f"Consulta recibida: {short}"
            )
        return (
            f"(Plantillas) No hay LLM local ni nube activos en este momento. "
            f"Tu consulta fue: {short}"
        )

    # ==================== UTILIDAD ====================

    def wait_if_busy(self, delay: float = 0.0) -> None:
        """Espera opcional (para test de timeout / no bloqueo)."""
        if delay > 0:
            time.sleep(delay)
