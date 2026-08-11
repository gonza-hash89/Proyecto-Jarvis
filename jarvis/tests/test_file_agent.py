"""
test_file_agent.py - Tests del File Agent (SEMANA 6, FASE 1)

Verifica:
- Contrato AgentBase (proceso, mensaje inválido, intención no soportada)
- Notas en SQLite (memories, clave note::)
- Tareas con estado (pendiente → completada)
- Recordatorios con fecha/hora
- Lectura y listado de archivos en data_dir (rutas seguras)
- Degradación elegante cuando el almacenamiento falla

Todas las pruebas usan directorios temporales: no tocan data/ ni la DB real.
"""

import sqlite3

import agents.file as file_mod
from agents.base import AgentBase
from agents.file import FileAgent


def _agent(tmp_path, db_ok=True):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "jarvis_memory.db"
    agent = FileAgent("file_agent", {"data_dir": str(data_dir), "db_path": str(db_path)})
    if not db_ok:
        agent._store = None
        agent._db_available = False
    return agent, data_dir


def _process(agent, intent, params=None, text=""):
    return agent.process({
        "intent": intent,
        "parameters": params or {},
        "text": text,
    })


def _db_rows(tmp_path):
    db = sqlite3.connect(tmp_path / "jarvis_memory.db")
    rows = db.execute("SELECT key, value, metadata FROM memories").fetchall()
    db.close()
    return rows


# ══════════════════ CONTRATO ══════════════════

def test_hereda_de_agentbase(tmp_path):
    agent, _ = _agent(tmp_path)
    assert isinstance(agent, AgentBase)


def test_mensaje_invalido(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = agent.process("hola")
    assert resp["status"] == "error"
    assert resp["agent"] == "file_agent"
    assert "Mensaje inv" in resp["data"]["result"]


def test_intencion_no_soportada(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "hack_the_pentagon")
    assert resp["status"] == "success"
    assert "en desarrollo" in resp["data"]["result"]


def test_get_info_capacidades(tmp_path):
    agent, _ = _agent(tmp_path)
    info = agent.get_info()
    assert "take_notes" in info["capabilities"]
    assert info["db_available"] is True


def test_inicializa_data_dir(tmp_path):
    data_dir = tmp_path / "data"
    _agent(tmp_path)
    assert data_dir.exists()


# ══════════════════ NOTAS (SQLite) ══════════════════

def test_take_notes_guarda_en_sqlite(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "take_notes", {"content": "comprar leche"})
    assert resp["status"] == "success"
    assert "Nota guardada" in resp["data"]["result"]
    assert resp["data"]["saved"] is True

    rows = _db_rows(tmp_path)
    assert len(rows) == 1
    key, value, metadata = rows[0]
    assert key.startswith("note::")
    assert "comprar leche" in value
    assert metadata


def test_take_notes_desde_texto(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "take_notes", text="anota comprar leche")
    assert "comprar leche" in resp["data"]["result"]


def test_take_notes_sin_contenido(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "take_notes")
    assert "qué quieres que anote" in resp["data"]["result"].lower()
    assert _db_rows(tmp_path) == []


def test_take_notes_sin_db(tmp_path):
    agent, _ = _agent(tmp_path, db_ok=False)
    resp = _process(agent, "take_notes", {"content": "hola"})
    assert resp["data"]["saved"] is False
    assert "no pude guardar" in resp["data"]["result"].lower()# ══════════════════ TAREAS (estado) ══════════════════

def test_create_task_pendiente(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "create_task", {"task_description": "llamar al médico"})
    assert resp["data"]["status"] == "pendiente"
    assert "Tarea agregada" in resp["data"]["result"]

    rows = _db_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][0].startswith("task::")


def test_create_task_desde_texto(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "create_task", text="agrega una tarea pagar internet")
    assert "pagar internet" in resp["data"]["result"]


def test_create_task_sin_tarea(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "create_task")
    assert "qué tarea" in resp["data"]["result"].lower()


def test_list_tasks_vacia(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "list_tasks")
    assert resp["data"]["count"] == 0
    assert "no tienes tareas" in resp["data"]["result"].lower()


def test_list_tasks_con_estado(tmp_path):
    agent, _ = _agent(tmp_path)
    _process(agent, "create_task", {"task_description": "hacer ejercicio"})
    _process(agent, "create_task", {"task_description": "leer un libro"})
    _process(agent, "complete_task", {"task": "hacer ejercicio"})

    resp = _process(agent, "list_tasks")
    assert resp["data"]["count"] == 2
    result = resp["data"]["result"]
    assert "hacer ejercicio" in result
    assert "leer un libro" in result


def test_complete_task(tmp_path):
    agent, _ = _agent(tmp_path)
    _process(agent, "create_task", {"task_description": "hacer ejercicio"})
    resp = _process(agent, "complete_task", {"task": "hacer ejercicio"})
    assert resp["data"]["status"] == "completada"
    assert "Tarea completada" in resp["data"]["result"]


def test_complete_task_no_encontrada(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "complete_task", {"task": "no existe"})
    assert "no encontré esa tarea" in resp["data"]["result"].lower() or "no tienes tareas" in resp["data"]["result"].lower()


def test_complete_task_por_key(tmp_path):
    agent, _ = _agent(tmp_path)
    created = _process(agent, "create_task", {"task_description": "comprar pan"})
    key = created["data"]["key"]
    resp = _process(agent, "complete_task", {"key": key})
    assert resp["data"]["status"] == "completada"


# ══════════════════ RECORDATORIOS ══════════════════

def test_reminder_set_con_hora(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "reminder_set", {"task": "reunión", "time": "18:30"})
    assert resp["data"]["saved"] is True
    assert resp["data"]["source"] == "parsed"
    assert "reunión" in resp["data"]["result"]
    assert "18:30" in resp["data"]["result"]

    rows = _db_rows(tmp_path)
    assert rows[0][0].startswith("reminder::")


def test_reminder_set_sin_hora_usa_default(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "reminder_set", {"task": "tomar agua"})
    assert resp["data"]["saved"] is True
    assert resp["data"]["source"] == "default"


def test_reminder_set_en_minutos(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "reminder_set", {"task": "llamar", "time": "en 10 minutos"})
    assert resp["data"]["saved"] is True
    assert resp["data"]["source"] == "parsed"


def test_reminder_set_sin_tarea(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "reminder_set")
    assert "qué quieres que te recuerde" in resp["data"]["result"].lower()


# ══════════════════ ARCHIVOS (data_dir) ══════════════════

def test_read_file_ok(tmp_path):
    agent, data_dir = _agent(tmp_path)
    (data_dir / "notas.txt").write_text("contenido de prueba", encoding="utf-8")
    resp = _process(agent, "read_file", {"filename": "notas.txt"})
    assert resp["data"]["result"] == "contenido de prueba"
    assert resp["data"]["filename"] == "notas.txt"


def test_read_file_desde_texto(tmp_path):
    agent, data_dir = _agent(tmp_path)
    (data_dir / "ideas.md").write_text("idea genial", encoding="utf-8")
    resp = _process(agent, "read_file", text="lee el archivo ideas.md")
    assert resp["data"]["result"] == "idea genial"


def test_read_file_no_existe(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "read_file", {"filename": "no_existe.txt"})
    assert "no encontré" in resp["data"]["result"].lower()


def test_read_file_sin_nombre(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "read_file")
    assert "qué archivo" in resp["data"]["result"].lower()


def test_read_file_path_traversal_bloqueado(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "read_file", {"filename": "../../../etc/passwd"})
    assert resp["data"]["result"] == "Nombre de archivo inválido: ../../../etc/passwd"


def test_list_folder_ok(tmp_path):
    agent, data_dir = _agent(tmp_path)
    (data_dir / "a.txt").write_text("a", encoding="utf-8")
    (data_dir / "b.md").write_text("b", encoding="utf-8")
    resp = _process(agent, "list_folder")
    assert resp["data"]["files"] == ["a.txt", "b.md"]
    assert "a.txt" in resp["data"]["result"]


def test_list_folder_vacia(tmp_path):
    agent, _ = _agent(tmp_path)
    resp = _process(agent, "list_folder")
    assert resp["data"]["files"] == []
    assert "vacía" in resp["data"]["result"]


def test_list_folder_excluye_db(tmp_path):
    agent, _ = _agent(tmp_path)
    (agent.data_dir / "nota.txt").write_text("x", encoding="utf-8")
    resp = _process(agent, "list_folder")
    assert "nota.txt" in resp["data"]["files"]
    assert not any(f.endswith(".db") for f in resp["data"]["files"])


# ══════════════════ UTILIDADES ══════════════════

def test_after_phrase():
    assert FileAgent._after_phrase("anota comprar leche", file_mod._NOTE_MARKERS) == "comprar leche"
    assert FileAgent._after_phrase("", file_mod._NOTE_MARKERS) == ""
    assert FileAgent._after_phrase("sin marcador aquí", file_mod._NOTE_MARKERS) == "sin marcador aquí"


def test_safe_path(tmp_path):
    agent, _ = _agent(tmp_path)
    assert agent._safe_path("hola.txt") is not None
    assert agent._safe_path("../hola.txt") is None
    assert agent._safe_path("") is None
    assert agent._safe_path(".") is None
    assert agent._safe_path("..") is None
