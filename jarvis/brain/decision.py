"""
decision.py - Motor de decisiones para Jarvis

El corazón estratégico del sistema. Toma intenciones reconocidas y decide:
  1. Qué acción ejecutar
  2. En qué orden (prioridades)
  3. Qué agente es responsable
  4. Cómo manejar conflictos

Filosofía:
- Mejor lento y bien, que rápido y mal
- Las decisiones se basan en confianza + contexto + memoria
- Cada decisión es trazable (logging completo)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from datetime import datetime
import json
from abc import ABC, abstractmethod

from core.logger import JarvisLogger, AgentLogger, EventLogger
from core.config import get_config, DecisionConfig


# ==================== TIPOS DE DECISIONES ====================

class IntentPriority(Enum):
    """Niveles de prioridad de las intenciones"""
    CRITICAL = 5    # Requiere atención inmediata
    HIGH = 4        # Importante, ejecutar pronto
    NORMAL = 3      # Ejecución normal
    LOW = 2         # Puede esperar
    BACKGROUND = 1  # Ejecución en segundo plano


class AgentType(Enum):
    """Tipos de agentes disponibles"""
    VOICE = "voice_agent"           # Síntesis de voz
    DIALOG = "dialog_agent"         # Generación de respuestas
    MEMORY = "memory_agent"         # Gestión de memoria
    SYSTEM = "system_agent"         # Control del sistema
    WEB = "web_agent"               # Búsqueda en internet
    FILE = "file_agent"             # Gestión de archivos
    CALENDAR = "calendar_agent"     # Gestión de agenda
    CREATIVE = "creative_agent"     # Tareas creativas


# ==================== ESTRUCTURAS DE DATOS ====================

@dataclass
class Intent:
    """Una intención reconocida del usuario"""
    id: str
    name: str
    confidence: float  # 0.0 - 1.0
    parameters: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Valida los valores"""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0 and 1, got {self.confidence}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para serialización"""
        return {
            "id": self.id,
            "name": self.name,
            "confidence": self.confidence,
            "parameters": self.parameters,
            "raw_text": self.raw_text,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class Decision:
    """Una decisión tomada por el motor"""
    id: str
    intent: Intent
    selected_agent: AgentType
    priority: IntentPriority
    confidence: float  # Confianza en esta decisión
    reasoning: str  # Por qué se tomó esta decisión
    dependencies: List[str] = field(default_factory=list)  # IDs de otras decisiones que debe esperar
    actions: List[str] = field(default_factory=list)  # Acciones específicas a ejecutar
    timestamp: datetime = field(default_factory=datetime.now)
    status: str = "pending"  # pending, executing, completed, failed
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        return {
            "id": self.id,
            "intent": self.intent.to_dict(),
            "selected_agent": self.selected_agent.value,
            "priority": self.priority.name,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "dependencies": self.dependencies,
            "actions": self.actions,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status
        }


@dataclass
class DecisionContext:
    """Contexto en el que se toman decisiones"""
    user_id: str = ""
    session_id: str = ""
    previous_intents: List[Intent] = field(default_factory=list)
    active_decisions: List[Decision] = field(default_factory=list)
    system_state: Dict[str, Any] = field(default_factory=dict)
    available_agents: List[AgentType] = field(default_factory=lambda: list(AgentType))
    constraints: Dict[str, Any] = field(default_factory=dict)
    
    def get_recent_intents(self, limit: int = 5) -> List[Intent]:
        """Obtiene las últimas N intenciones"""
        return self.previous_intents[-limit:]
    
    def get_agent_availability(self, agent: AgentType) -> bool:
        """Verifica si un agente está disponible"""
        return agent in self.available_agents
    
    def add_active_decision(self, decision: Decision) -> None:
        """Agrega una decisión activa al contexto"""
        self.active_decisions.append(decision)


# ==================== REGLAS DE DECISIÓN ====================

class DecisionRule(ABC):
    """Clase base para reglas de decisión"""
    
    def __init__(self, name: str, weight: float = 1.0):
        """
        Inicializa la regla.
        
        Args:
            name: Nombre descriptivo de la regla
            weight: Peso de esta regla en la decisión final (0.0 - 1.0)
        """
        self.name = name
        self.weight = weight
        self.logger = JarvisLogger.get_logger(f"rule_{name}")
    
    @abstractmethod
    def evaluate(self, intent: Intent, context: DecisionContext) -> Tuple[float, str]:
        """
        Evalúa si esta regla aplica.
        
        Args:
            intent: La intención a evaluar
            context: Contexto de decisión
        
        Returns:
            (score, reason) - Score de 0.0 a 1.0 y razón de la evaluación
        """
        pass


class ConfidenceRule(DecisionRule):
    """Evalúa basada en la confianza de la intención"""
    
    def evaluate(self, intent: Intent, context: DecisionContext) -> Tuple[float, str]:
        """La confianza del intent es crucial"""
        reason = f"Intent confidence: {intent.confidence:.2%}"
        return intent.confidence, reason


class RecencyRule(DecisionRule):
    """Las intenciones recientes son más relevantes"""
    
    def evaluate(self, intent: Intent, context: DecisionContext) -> Tuple[float, str]:
        """Recencia: intenciones más nuevas puntúan más"""
        if not context.previous_intents:
            return 1.0, "First intent"
        
        # Calcular tiempo desde la última intención similar
        time_diff = (datetime.now() - intent.timestamp).total_seconds()
        decay = 1.0 / (1.0 + time_diff / 60.0)  # Decae con el tiempo
        
        reason = f"Recency decay: {decay:.2%} (time elapsed: {time_diff:.0f}s)"
        return decay, reason


class ContextRelevanceRule(DecisionRule):
    """Intenciones relevantes al contexto reciente"""
    
    def evaluate(self, intent: Intent, context: DecisionContext) -> Tuple[float, str]:
        """Evalúa relevancia basada en historia reciente"""
        recent = context.get_recent_intents(3)
        
        if not recent:
            return 0.8, "No recent context"
        
        # Si la intención es similar a las recientes, es más relevante
        relevance = sum(
            1.0 if r.name == intent.name else 0.5
            for r in recent
        ) / len(recent)
        
        reason = f"Context relevance: {relevance:.2%} (matches {len(recent)} recent intents)"
        return relevance, reason


class PriorityRule(DecisionRule):
    """Intenciones críticas siempre tienen precedencia"""
    
    def evaluate(self, intent: Intent, context: DecisionContext) -> Tuple[float, str]:
        """Evalúa basada en la prioridad"""
        # Mapear tipos de intención a prioridades
        priority_map = {
            "emergency": IntentPriority.CRITICAL,
            "urgent": IntentPriority.HIGH,
            "normal": IntentPriority.NORMAL,
            "background": IntentPriority.BACKGROUND,
        }
        
        # Determinar prioridad (por defecto NORMAL)
        priority = priority_map.get(intent.parameters.get("priority", "normal"), IntentPriority.NORMAL)
        score = priority.value / 5.0  # Normalizar a 0.0-1.0
        
        reason = f"Priority level: {priority.name} (score: {score:.2%})"
        return score, reason


class AgentAvailabilityRule(DecisionRule):
    """Verifica que el agente esté disponible"""
    
    def __init__(self, required_agent: AgentType):
        super().__init__(f"availability_{required_agent.value}")
        self.required_agent = required_agent
    
    def evaluate(self, intent: Intent, context: DecisionContext) -> Tuple[float, str]:
        """Verifica disponibilidad del agente"""
        available = context.get_agent_availability(self.required_agent)
        score = 1.0 if available else 0.0
        reason = f"Agent {self.required_agent.value} {'available' if available else 'unavailable'}"
        return score, reason


# ==================== ESTRATEGIAS DE DECISIÓN ====================

class DecisionStrategy(ABC):
    """Clase base para estrategias de decisión"""
    
    def __init__(self, config: DecisionConfig, logger: AgentLogger = None):
        """
        Inicializa la estrategia.
        
        Args:
            config: Configuración de decisiones
            logger: Logger opcional
        """
        self.config = config
        self.logger = logger or AgentLogger("decision_engine")
    
    @abstractmethod
    def decide(
        self, 
        intents: List[Intent], 
        context: DecisionContext
    ) -> Optional[Decision]:
        """
        Toma una decisión basada en intenciones y contexto.
        
        Args:
            intents: Lista de intenciones a considerar
            context: Contexto de decisión
        
        Returns:
            La decisión seleccionada o None si no se puede decidir
        """
        pass


class ConfidenceBasedStrategy(DecisionStrategy):
    """
    Estrategia basada en confianza.
    Elige la intención con mayor confianza ponderada.
    """
    
    def __init__(self, config: DecisionConfig, logger: AgentLogger = None):
        super().__init__(config, logger)
        
        # Registrar reglas de evaluación
        self.rules = [
            ConfidenceRule("confidence", weight=0.5),
            RecencyRule("recency", weight=0.2),
            PriorityRule("priority", weight=0.3),
        ]
    
    def decide(
        self, 
        intents: List[Intent], 
        context: DecisionContext
    ) -> Optional[Decision]:
        """Toma decisión basada en puntajes de confianza"""
        
        if not intents:
            self.logger.warning("No intents to decide on")
            return None
        
        # Evaluar cada intención
        best_intent = None
        best_score = 0.0
        best_reasoning = []
        
        for intent in intents:
            weighted_score = 0.0
            reasoning = []
            
            # Aplicar cada regla
            for rule in self.rules:
                score, reason = rule.evaluate(intent, context)
                weighted = score * rule.weight
                weighted_score += weighted
                reasoning.append(f"{rule.name}: {reason} (weight: {rule.weight})")
            
            # Normalizar por suma de pesos
            total_weight = sum(r.weight for r in self.rules)
            weighted_score /= total_weight
            
            self.logger.debug(
                f"Intent '{intent.name}' scored: {weighted_score:.2%}",
                rules="\n  ".join(reasoning)
            )
            
            if weighted_score > best_score:
                best_score = weighted_score
                best_intent = intent
                best_reasoning = reasoning
        
        if best_intent is None or best_score < self.config.confidence_threshold:
            self.logger.warning(
                f"No intent met confidence threshold ({self.config.confidence_threshold})"
            )
            return None
        
        # Crear la decisión
        decision = self._create_decision(
            best_intent,
            best_score,
            "\n".join(best_reasoning)
        )
        
        self.logger.info(
            f"Decision made: {decision.selected_agent.value} for intent '{best_intent.name}'",
            confidence=f"{decision.confidence:.2%}",
            priority=decision.priority.name
        )
        
        return decision
    
    def _create_decision(
        self, 
        intent: Intent, 
        score: float, 
        reasoning: str
    ) -> Decision:
        """Crea una estructura Decision a partir de una intención"""
        
        # Mapear intención a agente (debe coincidir con los nombres reales del IntentRecognizer)
        agent_map = {
            # Entretenimiento / contenido
            "play_music": AgentType.DIALOG,
            "watch_videos": AgentType.SYSTEM,
            "tell_joke": AgentType.DIALOG,
            # Información
            "search_info": AgentType.WEB,
            "time_query": AgentType.SYSTEM,
            "date_query": AgentType.SYSTEM,
            # Sistema
            "system_control": AgentType.SYSTEM,
            "open_application": AgentType.SYSTEM,
            "take_screenshot": AgentType.SYSTEM,
            # Identidad
            "change_name": AgentType.DIALOG,
            "exit": AgentType.SYSTEM,
        }
        
        # Seleccionar agente
        agent = agent_map.get(
            intent.name, 
            AgentType.DIALOG  # Por defecto
        )
        
        # Determinar prioridad
        priority_val = intent.parameters.get("priority", "normal")
        priority_map = {
            "critical": IntentPriority.CRITICAL,
            "high": IntentPriority.HIGH,
            "normal": IntentPriority.NORMAL,
            "low": IntentPriority.LOW,
            "background": IntentPriority.BACKGROUND,
        }
        priority = priority_map.get(priority_val, IntentPriority.NORMAL)
        
        decision = Decision(
            id=f"dec_{intent.id}_{datetime.now().timestamp()}",
            intent=intent,
            selected_agent=agent,
            priority=priority,
            confidence=score,
            reasoning=reasoning,
            actions=[intent.name]
        )
        
        return decision


class ContextAwareStrategy(DecisionStrategy):
    """
    Estrategia sensible al contexto.
    Considera el historial y el estado del sistema (CONCIENCIA N3).
    """

    def _inherit_entities(
        self,
        current: Intent,
        context: DecisionContext,
    ) -> List[str]:
        """Completa entidades faltantes de la intención actual con las del
        turno anterior (elipsis: "¿y pasado mañana?" hereda la ciudad)."""
        inherited: List[str] = []
        params = current.parameters
        if not isinstance(params, dict):
            params = {}
            current.parameters = params
        for prev in context.get_recent_intents(3):
            if prev is current:
                continue
            prev_params = getattr(prev, "parameters", None)
            if not isinstance(prev_params, dict):
                continue
            for key, value in prev_params.items():
                if key not in params:
                    params[key] = value
                    inherited.append(key)
        return inherited

    def decide(
        self,
        intents: List[Intent],
        context: DecisionContext
    ) -> Optional[Decision]:
        """Toma decisión considerando contexto detallado"""

        if not intents:
            return None

        # Elipsis de entidades: heredar del turno anterior (N3)
        inherited = self._inherit_entities(intents[0], context)

        # Para esta versión, usamos confidence_based como base
        base_strategy = ConfidenceBasedStrategy(self.config, self.logger)
        decision = base_strategy.decide(intents, context)

        if decision:
            # Ajustar según contexto
            decision.reasoning += "\n[Context-aware adjustments applied]"
            if inherited:
                decision.reasoning += (
                    f"\n[Context: entidades heredadas del turno anterior: "
                    f"{', '.join(inherited)}]"
                )

        return decision


# ==================== MOTOR DE DECISIONES ====================

class DecisionEngine:
    """
    Motor de decisiones central de Jarvis.
    
    Responsabilidades:
    - Recibir intenciones reconocidas
    - Aplicar reglas de decisión
    - Gestionar conflictos
    - Ejecutar o encolar decisiones
    - Mantener histórico de decisiones
    """
    
    def __init__(
        self, 
        config: Optional[DecisionConfig] = None,
        strategy: Optional[str] = None
    ):
        """
        Inicializa el motor de decisiones.
        
        Args:
            config: Configuración de decisiones
            strategy: Estrategia a usar ("confidence_based" o "context_aware")
        """
        self.config = config or get_config().decision
        self.logger = AgentLogger("decision_engine", agent_id="dec_001")
        self.event_logger = EventLogger()
        
        # Inicializar estrategia
        strategy_name = strategy or self.config.strategy
        if strategy_name == "confidence_based":
            self.strategy = ConfidenceBasedStrategy(self.config, self.logger)
        elif strategy_name == "context_aware":
            self.strategy = ContextAwareStrategy(self.config, self.logger)
        else:
            self.strategy = ConfidenceBasedStrategy(self.config, self.logger)
        
        # Estado
        self._decision_history: List[Decision] = []
        self._pending_decisions: List[Decision] = []
        self._context = DecisionContext()
        
        self.logger.info("Decision engine initialized", strategy=strategy_name)
    
    def decide(
        self, 
        intents: List[Intent], 
        context: Optional[DecisionContext] = None
    ) -> Optional[Decision]:
        """
        Toma una decisión basada en las intenciones proporcionadas.
        
        Args:
            intents: Lista de intenciones a considerar
            context: Contexto de decisión (si None, usa el almacenado)
        
        Returns:
            La decisión tomada o None
        """
        
        # Usar contexto proporcionado o el almacenado
        if context:
            self._context = context
        
        # Actualizar contexto con las intenciones actuales
        self._context.previous_intents.extend(intents)
        
        self.logger.info(f"Processing {len(intents)} intent(s)")
        
        # Usar estrategia para decidir
        decision = self.strategy.decide(intents, self._context)
        
        if decision:
            self._decision_history.append(decision)
            self._pending_decisions.append(decision)
            
            # Log de evento
            self.event_logger.log_event("decision_made", {
                "decision_id": decision.id,
                "intent": decision.intent.name,
                "agent": decision.selected_agent.value,
                "confidence": f"{decision.confidence:.2%}"
            })
        
        return decision
    
    def get_pending_decisions(self) -> List[Decision]:
        """Obtiene las decisiones pendientes de ejecutar"""
        return self._pending_decisions.copy()
    
    def mark_decision_executed(self, decision_id: str) -> bool:
        """
        Marca una decisión como ejecutada.
        
        Args:
            decision_id: ID de la decisión
        
        Returns:
            True si se marcó, False si no se encontró
        """
        for i, decision in enumerate(self._pending_decisions):
            if decision.id == decision_id:
                decision.status = "completed"
                del self._pending_decisions[i]
                
                self.event_logger.log_event("decision_executed", {
                    "decision_id": decision_id
                })
                
                return True
        
        return False
    
    def get_decision_history(self, limit: int = 10) -> List[Decision]:
        """Obtiene el historial de decisiones recientes"""
        return self._decision_history[-limit:]
    
    def get_context(self) -> DecisionContext:
        """Obtiene el contexto actual de decisión"""
        return self._context
    
    def export_decision_history(self, filepath: str) -> None:
        """Exporta el historial de decisiones a JSON"""
        history = [d.to_dict() for d in self._decision_history]
        with open(filepath, 'w') as f:
            json.dump(history, f, indent=2)
        
        self.logger.info(f"Decision history exported to {filepath}")


# ==================== UTILIDADES ====================

def resolve_conflicts(decisions: List[Decision]) -> Decision:
    """
    Resuelve conflictos cuando hay múltiples decisiones válidas.
    
    Estrategia:
    1. Intenciones críticas siempre ganan
    2. Confianza más alta gana
    3. Intenciones recientes ganan
    
    Args:
        decisions: Lista de decisiones en conflicto
    
    Returns:
        La decisión ganadora
    """
    if not decisions:
        raise ValueError("No decisions to resolve")
    
    if len(decisions) == 1:
        return decisions[0]
    
    # Ordenar por prioridad (descendente)
    decisions_sorted = sorted(
        decisions,
        key=lambda d: (d.priority.value, d.confidence),
        reverse=True
    )
    
    return decisions_sorted[0]


def can_execute_in_parallel(dec1: Decision, dec2: Decision) -> bool:
    """
    Determina si dos decisiones pueden ejecutarse en paralelo.
    
    Args:
        dec1, dec2: Decisiones a comparar
    
    Returns:
        True si pueden ejecutarse juntas
    """
    # Diferentes agentes pueden ejecutarse en paralelo
    if dec1.selected_agent != dec2.selected_agent:
        return True
    
    # Mismo agente: revisar dependencias
    return dec2.id not in dec1.dependencies
