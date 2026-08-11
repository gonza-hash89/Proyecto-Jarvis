"""
agents/factory.py - Fábrica de agentes (SEMANA 5, FASE 0)

Crea agentes según el AgentType con degradación elegante:
- Si el agente no está implementado todavía → devuelve None (sin crashes)
- Los agentes concretos deben aceptar (agent_type: str, config: dict)
  y llamar a super().__init__(name=agent_type, agent_type=agent_type, config=config)
"""

import importlib
from typing import Any, Dict, Optional

from brain.decision import AgentType
from core.logger import JarvisLogger

from agents.base import AgentBase


class AgentFactory:
    """Crea instancias de agentes según AgentType."""

    # AgentType -> (módulo, clase) de los agentes de Semana 5 y 6
    _AGENT_MAP: Dict[AgentType, tuple] = {
        AgentType.SYSTEM: ("agents.system", "SystemAgent"),
        AgentType.WEB: ("agents.web", "WebAgent"),
        AgentType.DIALOG: ("agents.dialog", "DialogAgent"),
        AgentType.FILE: ("agents.file", "FileAgent"),
        AgentType.VOICE: ("agents.voice", "VoiceAgent"),
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = config or {}
        self.logger = JarvisLogger.get_logger("AgentFactory")

    def create(
        self,
        agent_type: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentBase]:
        """Crea un agente del tipo indicado.

        Args:
            agent_type: AgentType o su valor string (ej: "system_agent").
            config: Configuración específica del agente (se fusiona con la global).

        Returns:
            Instancia del agente, o None si no está disponible.
        """
        if isinstance(agent_type, str):
            try:
                agent_type = AgentType(agent_type)
            except ValueError:
                self.logger.warning(f"Tipo de agente desconocido: {agent_type}")
                return None

        entry = self._AGENT_MAP.get(agent_type)
        if entry is None:
            self.logger.warning(
                f"Agente {agent_type.value} no soportado en esta fase"
            )
            return None

        module_name, class_name = entry
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            self.logger.warning(f"Agente {class_name} no disponible: {e}")
            return None

        merged_config: Dict[str, Any] = {**self.config, **(config or {})}
        try:
            return cls(agent_type.value, merged_config)
        except Exception as e:
            self.logger.error(f"Error creando {class_name}: {e}")
            return None

    def supported_types(self) -> list:
        """Devuelve los AgentType soportados por la fábrica."""
        return list(self._AGENT_MAP.keys())
