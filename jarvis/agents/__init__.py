"""
agents - Paquete de agentes de Jarvis (SEMANA 5, FASE 0)

Estructura:
- base.py: AgentBase (extiende core.agent_base.Agent)
- registry.py: AgentRegistry (registro central por tipo)
- factory.py: AgentFactory (creación por AgentType con degradación elegante)
"""

from agents.base import AgentBase
from agents.factory import AgentFactory
from agents.registry import AgentRegistry

__all__ = ["AgentBase", "AgentRegistry", "AgentFactory"]
