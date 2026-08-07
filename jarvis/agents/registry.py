"""
agents/registry.py - Registro central de agentes (SEMANA 5, FASE 0)

Mantiene los agentes vivos por tipo, permitiendo:
- register(): registrar un agente
- get(): obtener un agente por tipo
- list(): listar agentes activos
- start_all()/stop_all(): ciclo de vida en lote
"""

from typing import Dict, List, Optional

from core.logger import JarvisLogger

from agents.base import AgentBase


class AgentRegistry:
    """Registro de agentes indexado por tipo (agent_type)."""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentBase] = {}
        self.logger = JarvisLogger.get_logger("AgentRegistry")

    def register(self, agent: Optional[AgentBase]) -> bool:
        """Registra un agente por su tipo.

        Args:
            agent: Agente a registrar (puede ser None si no se pudo crear).

        Returns:
            True si el agente quedó registrado.
        """
        if agent is None:
            self.logger.warning("No se registró un agente: la instancia es None")
            return False
        if agent.agent_type in self._agents:
            self.logger.warning(
                f"Agente {agent.agent_type} ya estaba registrado; se reemplaza"
            )
        self._agents[agent.agent_type] = agent
        self.logger.info(
            f"Agente {agent.name} ({agent.agent_type}) registrado"
        )
        return True

    def get(self, agent_type: str) -> Optional[AgentBase]:
        """Obtiene el agente registrado para un tipo (o None)."""
        return self._agents.get(agent_type)

    def list(self) -> List[AgentBase]:
        """Lista los agentes actualmente activos."""
        return [a for a in self._agents.values() if a.is_active]

    def list_all(self) -> List[AgentBase]:
        """Lista todos los agentes registrados (activos o no)."""
        return list(self._agents.values())

    def start_all(self) -> Dict[str, bool]:
        """Inicializa todos los agentes registrados.

        Returns:
            Dict con el resultado de initialize() por tipo.
        """
        results: Dict[str, bool] = {}
        for agent_type, agent in self._agents.items():
            try:
                results[agent_type] = agent.initialize()
            except Exception as e:  # pragma: no cover - defensivo
                agent.record_error("start_all", e)
                results[agent_type] = False
        return results

    def stop_all(self) -> None:
        """Detiene todos los agentes de forma ordenada."""
        for agent in self._agents.values():
            agent.stop()

    def clear(self) -> None:
        """Elimina todos los agentes del registro."""
        self._agents.clear()

    def get_count(self) -> int:
        """Número de agentes registrados."""
        return len(self._agents)
