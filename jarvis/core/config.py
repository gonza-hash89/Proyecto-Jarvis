"""
config.py - Configuración centralizada de Jarvis
Un único lugar para TODOS los settings
"""

import os
from typing import Dict, Any
from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass
class VoiceConfig:
    """Configuración del módulo de voz"""
    engine: str = "edge"  # edge (neural, recomendado), pyttsx3 (offline)
    voice: str = "es-ES-AlvaroNeural"  # Voz neural de edge-tts (masculina ES)
    rate: int = 150  # Velocidad de habla
    volume: float = 1.0  # Volumen (0-1)
    voice_id: int = 1  # 0=Masculina, 1=Femenina (solo fallback pyttsx3)
    language: str = "es-ES"
    timeout: int = 5  # Segundos para escuchar


@dataclass
class MemoryConfig:
    """Configuración del módulo de memoria"""
    enabled: bool = True
    max_history: int = 100
    storage_type: str = "json"  # json, sqlite, mongodb
    storage_path: str = "data/memory.json"
    context_window: int = 10  # Últimos N mensajes para contexto


@dataclass
class IntentConfig:
    """Configuración del reconocedor de intenciones"""
    provider: str = "gemini"  # gemini, openai, local
    confidence_threshold: float = 0.5
    use_fuzzy_matching: bool = True
    api_key: str = ""  # Se lee de environment variable
    model: str = "gemini-pro"


@dataclass
class DecisionConfig:
    """Configuración del motor de decisiones"""
    enabled: bool = True
    strategy: str = "confidence_based"  # confidence_based, context_aware
    confidence_threshold: float = 0.5  # Confianza mínima para aceptar una decisión
    max_retries: int = 3
    timeout: int = 30


@dataclass
class PlanningConfig:
    """Configuración del planificador de tareas"""
    enabled: bool = True
    max_subtasks: int = 10
    timeout: int = 60


@dataclass
class LoggingConfig:
    """Configuración del sistema de logging"""
    level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    format: str = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    file_path: str = "logs/jarvis.log"
    console_output: bool = True
    max_file_size: int = 10 * 1024 * 1024  # 10 MB


@dataclass
class SystemConfig:
    """Configuración general del sistema"""
    name: str = "Jarvis"
    version: str = "2.0.0"
    debug: bool = False
    auto_save: bool = True
    save_interval: int = 300  # Segundos
    max_concurrent_agents: int = 5


@dataclass
class AgentConfig:
    """Configuración de agentes"""
    enabled_agents: list = field(default_factory=lambda: [
        "voice_agent",
        "memory_agent",
        "dialog_agent",
        "system_agent",
        "web_agent"
    ])
    agent_timeout: int = 30
    retry_failed_agents: bool = True
    max_agent_retries: int = 3


@dataclass
class Config:
    """Configuración completa de Jarvis"""
    
    # Subsistemas
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    intent: IntentConfig = field(default_factory=IntentConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    planning: PlanningConfig = field(default_factory=PlanningConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    
    # Rutas importantes
    base_dir: str = field(default_factory=lambda: str(Path(__file__).parent.parent))
    data_dir: str = field(default_factory=lambda: "data")
    logs_dir: str = field(default_factory=lambda: "logs")
    
    def __post_init__(self):
        """Crear directorios necesarios después de inicializar"""
        self._create_directories()
        self._load_env_variables()
    
    def _create_directories(self):
        """Crea directorios necesarios si no existen"""
        dirs = [self.data_dir, self.logs_dir, "cache"]
        for dir_path in dirs:
            Path(dir_path).mkdir(exist_ok=True)
    
    def _load_env_variables(self):
        """Carga variables de environment"""
        # Intent API Key
        if gemini_key := os.getenv("GEMINI_API_KEY"):
            self.intent.api_key = gemini_key
        
        # Debug mode
        if debug := os.getenv("JARVIS_DEBUG"):
            self.system.debug = debug.lower() == "true"
        
        # Logging level
        if log_level := os.getenv("JARVIS_LOG_LEVEL"):
            self.logging.level = log_level
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte la configuración a diccionario"""
        return {
            "voice": self.voice.__dict__,
            "memory": self.memory.__dict__,
            "intent": self.intent.__dict__,
            "decision": self.decision.__dict__,
            "planning": self.planning.__dict__,
            "logging": self.logging.__dict__,
            "system": self.system.__dict__,
            "agent": self.agent.__dict__,
        }
    
    def save_to_file(self, filepath: str = "config.json"):
        """Guarda la configuración en un archivo JSON"""
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load_from_file(cls, filepath: str = "config.json") -> "Config":
        """Carga configuración desde archivo JSON"""
        if not Path(filepath).exists():
            return cls()
        
        with open(filepath, "r") as f:
            data = json.load(f)
        
        config = cls()
        # Aquí podrías actualizar config con los datos del archivo
        return config
    
    def __repr__(self) -> str:
        return f"Config(system={self.system.name} v{self.system.version})"


# Instancia global de configuración
_global_config: Config = None


def get_config() -> Config:
    """Obtiene la instancia global de configuración"""
    global _global_config
    if _global_config is None:
        _global_config = Config()
    return _global_config


def set_config(config: Config) -> None:
    """Establece la configuración global"""
    global _global_config
    _global_config = config
