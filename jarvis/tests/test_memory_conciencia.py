"""
test_memory_conciencia.py - Tests de CONCIENCIA N1 (memoria episódica)
y N2 (memoria semántica) — SEMANA 6, FASE 4

Cubre:
- brain/memory.py: LongTermMemory.get_recent / save_fact / get_facts /
  search_conversations (SQLite real en tmp_path, sin red)
- brain/intent_entities.py: EntityExtractor.extract_facts
- agents/dialog.py: DialogAgent con memoria inyectada (respuestas de memoria,
  persistencia de hechos, recuperación entre sesiones)

Declaración de honestidad: "memoria" aquí es recuperación real desde SQLite,
observable y testeable; no vivencia subjetiva.
"""

import asyncio
import json

from agents.dialog import DialogAgent, _run_coro
from brain.intent_entities import EntityExtractor
from brain.memory import LongTermMemory, MemoryManager


# ══════════════════════ DOBLES DE PRUEBA ══════════════════════

class _FakeMemory:
    """Doble que simula la interfaz de memoria que usa DialogAgent."""

    def __init__(self):
        self.facts = []
        self.turns = []

    def get_recent_sync(self, limit=5):
        return list(reversed(self.turns[-limit:])) if self.turns else []

    def get_facts_sync(self, fact_type=None):
        if fact_type:
            return [f for f in self.facts if f["fact_type"] == fact_type]
        return list(self.facts)

    async def save_fact(self, fact_type, fact_value, confidence=0.8, source=None):
        self.facts = [f for f in self.facts if f["fact_value"] != fact_value]
        self.facts.append({
            "fact_type": fact_type,
            "fact_value": fact_value,
            "confidence": confidence,
            "source": source,
        })
        return True

    async def search_conversations(self, query, limit=5):
        results = []
        for turn in self.turns:
            if query.lower() in turn["user_message"].lower():
                results.append(turn)
        return results[:limit]


def _agent_with_memory(memory=None, **cfg):
    base = {"memory": memory or _FakeMemory()}
    base.update(cfg)
    return DialogAgent("dialog_agent", base)


def _process(agent, intent, text="", params=None):
    return agent.process({
        "intent": intent,
        "text": text,
        "parameters": params or {},
    })


# ══════════════════════ N1: MEMORIA EPISÓDICA (SQLite) ══════════════════════

def test_save_y_get_recent(tmp_path):
    memory = LongTermMemory(str(tmp_path / "m.db"))
    _run_coro(memory.save_conversation("Hola", "Hola humano", "smalltalk"))
    _run_coro(memory.save_conversation("Clima?", "23 grados", "weather_query"))

    recent = _run_coro(memory.get_recent(5))
    assert len(recent) == 2
    assert recent[0]["user_message"] == "Clima?"
    assert recent[1]["user_message"] == "Hola"


def test_search_conversations_por_tema(tmp_path):
    memory = LongTermMemory(str(tmp_path / "m.db"))
    _run_coro(memory.save_conversation("¿De qué hablamos de Python?", "Instalamos paquetes", "smalltalk"))
    _run_coro(memory.save_conversation("¿Y el clima?", "Lluvioso", "weather_query"))

    results = _run_coro(memory.search_conversations("Python", limit=3))
    assert len(results) == 1
    assert "Python" in results[0]["user_message"]


def test_get_recent_vacio(tmp_path):
    memory = LongTermMemory(str(tmp_path / "m.db"))
    assert _run_coro(memory.get_recent(5)) == []


def test_memory_manager_sync_bridge(tmp_path):
    manager = MemoryManager(str(tmp_path / "m.db"))
    _run_coro(manager.save_conversation("Recuerda esto", "Listo", "take_notes"))
    recent = manager.get_recent_sync(5)
    assert recent[0]["user_message"] == "Recuerda esto"


# ══════════════════════ N2: MEMORIA SEMÁNTICA (hechos) ══════════════════════

def test_save_y_get_facts(tmp_path):
    memory = LongTermMemory(str(tmp_path / "m.db"))
    _run_coro(memory.save_fact("nombre", "Gonzalo", 0.95, "entity_extractor"))
    _run_coro(memory.save_fact("preferencia", "rock", 0.8, "entity_extractor"))

    facts = _run_coro(memory.get_facts())
    assert len(facts) == 2
    by_type = _run_coro(memory.get_facts("nombre"))
    assert by_type[0]["fact_value"] == "Gonzalo"
    assert by_type[0]["confidence"] == 0.95


def test_save_fact_deduplica(tmp_path):
    memory = LongTermMemory(str(tmp_path / "m.db"))
    _run_coro(memory.save_fact("preferencia", "rock", 0.8))
    _run_coro(memory.save_fact("preferencia", "rock", 0.9))
    facts = _run_coro(memory.get_facts("preferencia"))
    assert len(facts) == 1
    assert facts[0]["confidence"] == 0.9


def test_get_facts_vacio(tmp_path):
    memory = LongTermMemory(str(tmp_path / "m.db"))
    assert _run_coro(memory.get_facts("nombre")) == []


def test_memory_manager_facts_sync(tmp_path):
    manager = MemoryManager(str(tmp_path / "m.db"))
    manager.save_fact_sync("nombre", "Ana", 0.9)
    facts = manager.get_facts_sync("nombre")
    assert facts[0]["fact_value"] == "Ana"


# ══════════════════════ N2: EXTRACCIÓN DE HECHOS ══════════════════════

def test_extract_facts_nombre():
    facts = EntityExtractor().extract_facts("Me llamo Gonzalo y tengo 30 años")
    assert any(f["fact_type"] == "nombre" and f["fact_value"] == "Gonzalo" for f in facts)


def test_extract_facts_preferencia():
    facts = EntityExtractor().extract_facts("Me gusta el rock y el jazz")
    rock = [f for f in facts if f["fact_type"] == "preferencia"]
    assert rock and rock[0]["fact_value"] == "rock"


def test_extract_facts_preferencia_ingles():
    facts = EntityExtractor().extract_facts("I like coffee")
    pref = [f for f in facts if f["fact_type"] == "preferencia"]
    assert pref and pref[0]["fact_value"] == "coffee"


def test_extract_facts_lugar():
    facts = EntityExtractor().extract_facts("Vivo en Lima")
    lugar = [f for f in facts if f["fact_type"] == "lugar"]
    assert lugar and lugar[0]["fact_value"] == "Lima"


def test_extract_facts_sin_match():
    assert EntityExtractor().extract_facts("¿Qué hora es?") == []


def test_extract_facts_vacio():
    assert EntityExtractor().extract_facts("") == []


# ══════════════════════ DIALOG AGENT + MEMORIA ══════════════════════

def test_answer_user_name_desde_memoria():
    mem = _FakeMemory()
    mem.facts.append({"fact_type": "nombre", "fact_value": "Gonzalo",
                      "confidence": 0.95, "source": "entity_extractor"})
    agent = _agent_with_memory(mem)
    resp = _process(agent, "smalltalk", "¿cómo me llamo?")
    assert resp["data"]["source"] == "memory"
    assert "Gonzalo" in resp["data"]["result"]


def test_answer_user_name_sin_datos():
    agent = _agent_with_memory()
    resp = _process(agent, "smalltalk", "¿cómo me llamo?")
    assert resp["data"]["source"] == "templates"
    assert "nombre" in resp["data"]["result"].lower()


def test_answer_preferences_desde_memoria():
    mem = _FakeMemory()
    mem.facts.append({"fact_type": "preferencia", "fact_value": "rock",
                      "confidence": 0.8, "source": "entity_extractor"})
    agent = _agent_with_memory(mem)
    resp = _process(agent, "smalltalk", "¿qué música me gusta?")
    assert resp["data"]["source"] == "memory"
    assert "rock" in resp["data"]["result"]


def test_summarize_recent_desde_memoria():
    mem = _FakeMemory()
    mem.turns = [
        {"timestamp": "2026-08-09 10:00", "user_message": "Hola",
         "agent_response": "Hola humano", "intent": "smalltalk"},
    ]
    agent = _agent_with_memory(mem)
    resp = _process(agent, "smalltalk", "¿de qué hablamos?")
    assert resp["data"]["source"] == "memory"
    assert "Hola" in resp["data"]["result"]


def test_search_memory_recuerdos():
    mem = _FakeMemory()
    mem.turns = [
        {"timestamp": "2026-08-09 10:00", "user_message": "Te conté sobre Python",
         "agent_response": "Interesante", "intent": "smalltalk"},
    ]
    agent = _agent_with_memory(mem)
    resp = _process(agent, "smalltalk", "¿recuerdas cuando hablamos de Python?")
    assert resp["data"]["source"] == "memory"
    assert "Python" in resp["data"]["result"]


def test_remember_detected_facts_persiste():
    mem = _FakeMemory()
    agent = _agent_with_memory(mem)
    _process(agent, "smalltalk", "Me llamo Gonzalo")
    nombres = mem.get_facts_sync("nombre")
    assert any(f["fact_value"] == "Gonzalo" for f in nombres)


def test_recall_persiste_entre_instancias():
    """N2: el hecho persiste y lo recupera otra instancia del agente."""
    mem = _FakeMemory()
    _agent_with_memory(mem).process({
        "intent": "smalltalk", "text": "Me llamo Gonzalo", "parameters": {}
    })
    segundo = _agent_with_memory(mem)
    resp = _process(segundo, "smalltalk", "¿cómo me llamo?")
    assert "Gonzalo" in resp["data"]["result"]


def test_cambio_de_nombre_guarda_facto():
    mem = _FakeMemory()
    agent = _agent_with_memory(mem)
    _process(agent, "change_name", "a partir de ahora llámame JARVIS")
    nombres = mem.get_facts_sync("nombre")
    assert any(f["fact_value"].lower() == "jarvis" for f in nombres)


def test_sin_memoria_degrada_elegante():
    agent = DialogAgent("dialog_agent", {})
    resp = _process(agent, "smalltalk", "¿de qué hablamos?")
    assert resp["status"] == "success"
    assert "Todavía no hemos hablado" in resp["data"]["result"]


def test_memoria_llena_con_turnos_real_sqlite(tmp_path):
    """Integración: dialog agent + MemoryManager real sobre SQLite."""
    manager = MemoryManager(str(tmp_path / "m.db"))
    _run_coro(manager.save_conversation("Recuérdame llamar a Ana", "Anotado", "take_notes"))
    agent = _agent_with_memory(manager)
    resp = _process(agent, "smalltalk", "¿de qué hablamos?")
    assert resp["data"]["source"] == "memory"
    assert "llamar a Ana" in resp["data"]["result"]
