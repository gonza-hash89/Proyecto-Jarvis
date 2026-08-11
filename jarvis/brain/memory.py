"""
memory.py - Sistema de Memoria de Jarvis

Jarvis tiene DOS tipos de memoria:
1. SHORT TERM: Conversación actual (RAM rápido, se pierde al apagar)
2. LONG TERM: Todo lo que pasó antes (SQLite persistente)

MemoryManager coordina ambas y permite buscar, guardar y olvidar.

MÉTODOS DE BÚSQUEDA (IMPORTANTE):
- recall(key)    → Búsqueda EXACTA por clave (recall("user_name"))
- search(query)  → Búsqueda LIBRE en lenguaje natural (search("¿qué música me gusta?"))
"""

import sqlite3
import json
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import asyncio
from collections import deque
import logging


@dataclass
class MemoryItem:
    """Un item en memoria"""
    key: str
    value: Any
    importance: str  # "low", "normal", "high"
    timestamp: datetime
    metadata: Dict[str, Any]
    source: str  # "short_term" o "long_term"


@dataclass
class UserPreference:
    """Preferencia del usuario"""
    key: str
    value: str
    last_updated: datetime


@dataclass
class Entity:
    """Entidad extraída (persona, lugar, etc)"""
    entity_type: str
    entity_value: str
    mentions: int
    last_seen: datetime


class ShortTermMemory:
    """
    Memoria a corto plazo (RAM).
    Guarda la conversación actual. Se pierde al apagar.
    """

    def __init__(self, max_items: int = 100):
        self.max_items = max_items
        self.items: deque = deque(maxlen=max_items)
        self.context: Dict[str, Any] = {}

    def save(self, key: str, value: Any, metadata: Dict = None):
        item = MemoryItem(
            key=key,
            value=value,
            importance="normal",
            timestamp=datetime.now(),
            metadata=metadata or {},
            source="short_term"
        )
        self.items.append(item)

    def recall(self, key: str) -> Optional[MemoryItem]:
        """Recupera un item por clave exacta"""
        for item in self.items:
            if item.key == key:
                return item
        return None

    def recall_last(self, n: int = 5) -> List[MemoryItem]:
        return list(self.items)[-n:]

    def set_context(self, context_key: str, context_value: Any):
        self.context[context_key] = context_value

    def get_context(self, context_key: str = None) -> Any:
        if context_key:
            return self.context.get(context_key)
        return self.context

    def clear(self):
        self.items.clear()
        self.context.clear()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "name": "short_term",
            "total_items": len(self.items),
            "max_items": self.max_items,
            "context_keys": list(self.context.keys()),
            "oldest_entry": self.items[0].timestamp.isoformat() if self.items else None,
            "newest_entry": self.items[-1].timestamp.isoformat() if self.items else None
        }


class LongTermMemory:
    """
    Memoria a largo plazo (SQLite).
    Guarda todo persistentemente.
    """

    def __init__(self, db_path: str = "data/jarvis_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_db()

    def _initialize_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    user_message TEXT,
                    agent_response TEXT,
                    intent TEXT,
                    importance TEXT DEFAULT 'normal',
                    tags TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    preference_key TEXT UNIQUE,
                    preference_value TEXT,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT,
                    entity_value TEXT UNIQUE,
                    mentions INTEGER DEFAULT 1,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE,
                    value TEXT,
                    metadata TEXT,
                    importance TEXT DEFAULT 'normal',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_type TEXT,
                    fact_value TEXT,
                    confidence REAL DEFAULT 0.8,
                    source TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(fact_type, fact_value)
                )
            """)

            conn.commit()

    async def save(self, key: str, value: Any, metadata: Dict = None, importance: str = "normal"):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_sync, key, value, metadata, importance)

    def _save_sync(self, key: str, value: Any, metadata: Dict = None, importance: str = "normal"):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            value_json = json.dumps(value, default=str)
            metadata_json = json.dumps(metadata or {})
            cursor.execute("""
                INSERT OR REPLACE INTO memories (key, value, metadata, importance, accessed_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (key, value_json, metadata_json, importance))
            conn.commit()

    async def recall(self, key: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._recall_sync, key)

    def _recall_sync(self, key: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT key, value, metadata, importance, created_at, accessed_at
                FROM memories WHERE key = ?
            """, (key,))
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute("UPDATE memories SET accessed_at = CURRENT_TIMESTAMP WHERE key = ?", (key,))
            conn.commit()
            return {
                "key": row[0],
                "value": json.loads(row[1]),
                "metadata": json.loads(row[2]),
                "importance": row[3],
                "created_at": row[4],
                "accessed_at": row[5]
            }

    async def save_conversation(self, user_message: str, agent_response: str, intent: str = None, importance: str = "normal"):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_conversation_sync, user_message, agent_response, intent, importance)

    def _save_conversation_sync(self, user_message: str, agent_response: str, intent: str = None, importance: str = "normal"):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (user_message, agent_response, intent, importance)
                VALUES (?, ?, ?, ?)
            """, (user_message, agent_response, intent, importance))
            conn.commit()

    async def search_conversations(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_conversations_sync, query, limit)

    def _search_conversations_sync(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, user_message, agent_response, intent
                FROM conversations
                WHERE user_message LIKE ? OR agent_response LIKE ?
                ORDER BY timestamp DESC LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
            results = []
            for row in cursor.fetchall():
                results.append({
                    "timestamp": row[0],
                    "user_message": row[1],
                    "agent_response": row[2],
                    "intent": row[3]
                })
            return results

    async def search_memories(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_memories_sync, query, limit)

    def _search_memories_sync(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT key, value, metadata, importance, created_at
                FROM memories
                WHERE key LIKE ? OR value LIKE ?
                ORDER BY created_at DESC LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
            results = []
            for row in cursor.fetchall():
                results.append({
                    "key": row[0],
                    "value": json.loads(row[1]),
                    "metadata": json.loads(row[2]),
                    "importance": row[3],
                    "created_at": row[4]
                })
            return results

    # ── Memoria episódica (CONCIENCIA N1) ──

    async def get_recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Devuelve las últimas conversaciones (nuevas primero)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_recent_sync, limit)

    def _get_recent_sync(self, limit: int = 5) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, user_message, agent_response, intent
                FROM conversations ORDER BY id DESC LIMIT ?
            """, (limit,))
            return [
                {
                    "timestamp": row[0],
                    "user_message": row[1],
                    "agent_response": row[2],
                    "intent": row[3],
                }
                for row in cursor.fetchall()
            ]

    # ── Memoria semántica / hechos (CONCIENCIA N2) ──

    async def save_fact(
        self,
        fact_type: str,
        fact_value: str,
        confidence: float = 0.8,
        source: Optional[str] = None,
    ):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._save_fact_sync, fact_type, fact_value, confidence, source
        )

    def _save_fact_sync(
        self,
        fact_type: str,
        fact_value: str,
        confidence: float = 0.8,
        source: Optional[str] = None,
    ):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO facts (fact_type, fact_value, confidence, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(fact_type, fact_value) DO UPDATE SET
                    confidence = excluded.confidence,
                    source = excluded.source
            """, (fact_type, fact_value, confidence, source))
            conn.commit()

    async def get_facts(
        self, fact_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_facts_sync, fact_type)

    def _get_facts_sync(
        self, fact_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if fact_type:
                cursor.execute("""
                    SELECT fact_type, fact_value, confidence, source, created_at
                    FROM facts WHERE fact_type = ? ORDER BY created_at DESC
                """, (fact_type,))
            else:
                cursor.execute("""
                    SELECT fact_type, fact_value, confidence, source, created_at
                    FROM facts ORDER BY created_at DESC
                """)
            return [
                {
                    "fact_type": row[0],
                    "fact_value": row[1],
                    "confidence": row[2],
                    "source": row[3],
                    "created_at": row[4],
                }
                for row in cursor.fetchall()
            ]

    async def search_facts(
        self, query: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_facts_sync, query, limit)

    def _search_facts_sync(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT fact_type, fact_value, confidence, source, created_at
                FROM facts
                WHERE fact_value LIKE ? OR fact_type LIKE ?
                ORDER BY created_at DESC LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
            return [
                {
                    "fact_type": row[0],
                    "fact_value": row[1],
                    "confidence": row[2],
                    "source": row[3],
                    "created_at": row[4],
                }
                for row in cursor.fetchall()
            ]

    async def save_preference(self, key: str, value: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_preference_sync, key, value)

    def _save_preference_sync(self, key: str, value: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO user_profile (preference_key, preference_value, last_updated)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (key, value))
            conn.commit()

    async def get_user_profile(self) -> Dict[str, str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_user_profile_sync)

    def _get_user_profile_sync(self) -> Dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT preference_key, preference_value FROM user_profile")
            return {row[0]: row[1] for row in cursor.fetchall()}

    async def save_entity(self, entity_type: str, entity_value: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_entity_sync, entity_type, entity_value)

    def _save_entity_sync(self, entity_type: str, entity_value: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO entities (entity_type, entity_value, mentions)
                VALUES (?, ?, 1)
                ON CONFLICT(entity_value) DO UPDATE
                SET mentions = mentions + 1, last_seen = CURRENT_TIMESTAMP
            """, (entity_type, entity_value))
            conn.commit()

    async def cleanup_old_memories(self, days: int = 30):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._cleanup_old_memories_sync, days)

    def _cleanup_old_memories_sync(self, days: int = 30):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            cursor.execute("DELETE FROM conversations WHERE timestamp < ? AND importance = 'low'", (cutoff_date,))
            cursor.execute("DELETE FROM memories WHERE created_at < ? AND importance = 'low'", (cutoff_date,))
            conn.commit()

    async def get_stats(self) -> Dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_stats_sync)

    def _get_stats_sync(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM conversations")
            conversations_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM memories")
            memories_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM user_profile")
            preferences_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM entities")
            entities_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM facts")
            facts_count = cursor.fetchone()[0]
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            return {
                "name": "long_term",
                "conversations": conversations_count,
                "memories": memories_count,
                "preferences": preferences_count,
                "entities": entities_count,
                "facts": facts_count,
                "total_items": conversations_count + memories_count + preferences_count + entities_count + facts_count,
                "db_size_bytes": db_size,
                "db_path": str(self.db_path)
            }

    def close(self):
        """Sin conexión persistente que cerrar; se mantiene por simetría."""
        pass


class MemoryManager:
    """
    Orquestador de memoria.
    Coordina SHORT TERM + LONG TERM.
    """

    def __init__(self, db_path: str = "data/jarvis_memory.db"):
        self.short_term = ShortTermMemory(max_items=100)
        self.long_term = LongTermMemory(db_path)
        self.logger = logging.getLogger("Jarvis.memory")

    async def save(self, key: str, value: Any, importance: str = "normal", metadata: Dict = None, save_type: str = "both"):
        if save_type in ["short_term", "both"]:
            self.short_term.save(key, value, metadata)
        if save_type in ["long_term", "both"] and importance in ["normal", "high"]:
            await self.long_term.save(key, value, metadata, importance)

    async def recall(self, key: str) -> Optional[MemoryItem]:
        """Busca un item por CLAVE EXACTA."""
        item = self.short_term.recall(key)
        if item:
            return item
        item = await self.long_term.recall(key)
        if item:
            self.short_term.save(key, item["value"], item["metadata"])
            return MemoryItem(
                key=item["key"],
                value=item["value"],
                importance=item["importance"],
                timestamp=datetime.fromisoformat(item["created_at"]),
                metadata=item["metadata"],
                source="long_term"
            )
        return None

    async def search(self, query: str, limit: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        """Busca en memoria con LENGUAJE NATURAL."""
        conversaciones = await self.long_term.search_conversations(query, limit)
        memorias = await self.long_term.search_memories(query, limit)
        return {"conversaciones": conversaciones, "memorias": memorias}

    async def get_context(self) -> Dict[str, Any]:
        return self.short_term.get_context()

    async def set_context(self, context_key: str, context_value: Any):
        self.short_term.set_context(context_key, context_value)

    async def save_conversation(self, user_message: str, agent_response: str, intent: str = None):
        await self.long_term.save_conversation(user_message, agent_response, intent)
        self.short_term.save(
            key=f"conversation_{datetime.now().timestamp()}",
            value={"user": user_message, "agent": agent_response},
            metadata={"intent": intent}
        )

    async def get_user_profile(self) -> Dict[str, str]:
        return await self.long_term.get_user_profile()

    async def save_preference(self, key: str, value: str):
        await self.long_term.save_preference(key, value)

    async def save_entity(self, entity_type: str, entity_value: str):
        await self.long_term.save_entity(entity_type, entity_value)

    async def search_conversations(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        results = await self.search(query, limit)
        return results["conversaciones"]

    # ── Memoria episódica (CONCIENCIA N1) ──

    async def get_recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Últimas conversaciones persistentes (nuevas primero)."""
        return await self.long_term.get_recent(limit)

    def get_recent_sync(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Versión síncrona para uso en agentes (degradación elegante)."""
        return self.long_term._get_recent_sync(limit)

    # ── Memoria semántica / hechos (CONCIENCIA N2) ──

    async def save_fact(
        self,
        fact_type: str,
        fact_value: str,
        confidence: float = 0.8,
        source: Optional[str] = None,
    ):
        await self.long_term.save_fact(fact_type, fact_value, confidence, source)

    def save_fact_sync(
        self,
        fact_type: str,
        fact_value: str,
        confidence: float = 0.8,
        source: Optional[str] = None,
    ):
        self.long_term._save_fact_sync(fact_type, fact_value, confidence, source)

    async def get_facts(self, fact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        return await self.long_term.get_facts(fact_type)

    def get_facts_sync(self, fact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.long_term._get_facts_sync(fact_type)

    async def search_facts(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        return await self.long_term.search_facts(query, limit)

    def search_facts_sync(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        return self.long_term._search_facts_sync(query, limit)

    async def cleanup_old_memories(self, days: int = 30):
        await self.long_term.cleanup_old_memories(days)

    async def get_stats(self) -> Dict[str, Any]:
        return {
            "short_term": self.short_term.get_stats(),
            "long_term": await self.long_term.get_stats()
        }

    async def clear(self):
        self.short_term.clear()

    # ==================== Cierre ====================

    def close(self):
        self.long_term.close()
