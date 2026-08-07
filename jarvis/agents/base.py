"""
agents/base.py - Base común para todos los agentes de Jarvis (SEMANA 5, FASE 0)

Extiende el contrato de core/agent_base.Agent agregando:
- Ciclo de vida: initialize() y cleanup()
- Logging automático con JarvisLogger
- Manejo de errores estándar (record_error, _safe_call)
- Información extendida: get_info()

Los agentes concretos (system, web, dialog) heredan de AgentBase.
"""

from typing import Any, Callable, Dict, List, Optional

from core.agent_base import Agent
from core.logger import JarvisLogger


class AgentBase(Agent):
    """Base para todos los agentes de Jarvis con ciclo de vida y logging."""

    def __init__(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name, agent_type, config)
        self.logger = JarvisLogger.get_logger(name)
        self.initialized: bool = False
        self._errors: List[str] = []

    def initialize(self) -> bool:
        """Inicializa el agente (recursos, conexiones). Se sobreescribe.

        Returns:
            True si el agente quedó listo para operar.
        """
        self.initialized = True
        self.logger.info(f"Agente {self.name} inicializado")
        return True

    def cleanup(self) -> None:
        """Libera los recursos del agente. Se sobreescribe."""
        self.initialized = False
        self.logger.info(f"Agente {self.name} liberado")

    def stop(self) -> None:
        """Detiene el agente de forma segura, liberando recursos."""
        super().stop()
        try:
            self.cleanup()
        except Exception as e:  # pragma: no cover - depende de subclases
            self.record_error("cleanup", e)

    def get_info(self) -> Dict[str, Any]:
        """Información resumida del agente (estado + ciclo de vida)."""
        info = self.get_status()
        info["initialized"] = self.initialized
        info["errors"] = len(self._errors)
        return info

    def record_error(self, operation: str, exc: Exception) -> None:
        """Registra un error de forma estándar y lo loguea."""
        message = f"{operation}: {exc}"
        self._errors.append(message)
        self.logger.error(f"Error en {message}")

    def get_errors(self) -> List[str]:
        """Devuelve la lista de errores registrados."""
        return list(self._errors)

    def has_errors(self) -> bool:
        """Indica si el agente acumuló errores."""
        return bool(self._errors)

    def clear_errors(self) -> None:
        """Limpia el historial de errores del agente."""
        self._errors = []

    def _safe_call(self, operation: str, func: Callable, *args, **kwargs) -> Any:
        """Ejecuta una operación capturando y registrando errores.

        Returns:
            El resultado de func, o None si hubo un error.
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.record_error(operation, e)
            return None
