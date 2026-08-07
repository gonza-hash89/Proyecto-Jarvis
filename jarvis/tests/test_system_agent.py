"""
Tests de agents/system.py (SEMANA 5, FASE 1)

Verifica las acciones reales del SystemAgent usando mocks:
- control del sistema (apagar/reiniciar/bloquear/dormir)
- apertura de apps (web/local) y carpetas
- captura de pantalla
- volumen (degradación sin pycaw)
- papelera, procesos y fallback elegante
"""

import os
import subprocess

import agents.system as system_mod
from agents.base import AgentBase
from agents.system import SystemAgent


def _agent() -> SystemAgent:
    return SystemAgent()


def _msg(intent, params=None, text=""):
    return {"intent": intent, "parameters": params or {}, "text": text}


# ────────── Estructura ──────────

def test_hereda_de_agentbase():
    agent = _agent()
    assert isinstance(agent, AgentBase)
    assert agent.agent_type == "system_agent"


def test_mensaje_invalido():
    result = _agent().process("no soy un dict")
    assert result["status"] == "error"
    assert result["agent"] == "system_agent"


# ────────── Control del sistema ──────────

def test_apagar_sistema(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "system", lambda c: calls.append(c))
    result = _agent().process(_msg("system_control", {"action": "apagar"}))
    assert result["status"] == "success"
    assert calls and "shutdown /s" in calls[-1]


def test_reiniciar_sistema(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "system", lambda c: calls.append(c))
    result = _agent().process(_msg("system_control", {"action": "reiniciar"}))
    assert result["data"]["action"] == "reiniciar"
    assert "shutdown /r" in calls[-1]


def test_bloquear_sistema(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "system", lambda c: calls.append(c))
    result = _agent().process(_msg("system_control", {"action": "bloquear"}))
    assert result["data"]["action"] == "bloquear"
    assert "LockWorkStation" in calls[-1]


def test_dormir_sistema(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "system", lambda c: calls.append(c))
    result = _agent().process(_msg("system_control", {"action": "dormir"}))
    assert result["data"]["action"] == "dormir"
    assert "SetSuspendState" in calls[-1]


def test_control_por_texto(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "system", lambda c: calls.append(c))
    result = _agent().process(_msg("system_control", text="apaga la computadora"))
    assert "shutdown /s" in calls[-1]


def test_lock_session(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "system", lambda c: calls.append(c))
    result = _agent().process(_msg("lock_session"))
    assert "LockWorkStation" in calls[-1]


# ────────── Aplicaciones y carpetas ──────────

def test_abrir_app_web(monkeypatch):
    opened = []
    monkeypatch.setattr(system_mod.webbrowser, "open", lambda url: opened.append(url))
    result = _agent().process(_msg("open_application", {"application": "google"}))
    assert result["status"] == "success"
    assert opened and "google.com" in opened[0]


def test_abrir_app_local(monkeypatch):
    started = []
    monkeypatch.setattr(os, "startfile", lambda p: started.append(p))
    result = _agent().process(_msg("open_application", {"application": "notepad"}))
    assert started == ["notepad"]


def test_abrir_app_inexistente(monkeypatch):
    def fake_startfile(p):
        raise FileNotFoundError(p)
    monkeypatch.setattr(os, "startfile", fake_startfile)
    result = _agent().process(_msg("open_application", {"application": "appxyz"}))
    assert "No encontré" in result["data"]["result"]


def test_abrir_carpeta(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(os, "startfile", lambda p: started.append(p))
    result = _agent().process(_msg("open_folder", {"path": str(tmp_path)}))
    assert result["status"] == "success"
    assert started and started[0] == str(tmp_path)


def test_abrir_carpeta_inexistente():
    result = _agent().process(_msg("open_folder", {"path": "Z:\\no_existe_xyz"}))
    assert "No encontré" in result["data"]["result"]


# ────────── Captura ──────────

class _FakeImage:
    def __init__(self):
        self.path = None

    def save(self, path):
        self.path = path
        with open(path, "w", encoding="utf-8") as f:
            f.write("fake")


class _FakePyautogui:
    def screenshot(self):
        return _FakeImage()


def test_screenshot_guarda(monkeypatch, tmp_path):
    fake_img = _FakeImage()
    fake_pg = _FakePyautogui()
    fake_pg.screenshot = lambda: fake_img
    monkeypatch.setattr(system_mod, "_PYAUTOGUI_AVAILABLE", True)
    monkeypatch.setattr(system_mod, "pyautogui", fake_pg)
    result = _agent().process(_msg("take_screenshot", {"directory": str(tmp_path)}))
    assert result["status"] == "success"
    assert fake_img.path and fake_img.path.endswith(".png")
    assert os.path.isfile(fake_img.path)


def test_screenshot_sin_pyautogui(monkeypatch):
    monkeypatch.setattr(system_mod, "_PYAUTOGUI_AVAILABLE", False)
    result = _agent().process(_msg("take_screenshot"))
    assert "no está disponible" in result["data"]["result"]


# ────────── Volumen ──────────

def test_volumen_en_desarrollo_sin_pycaw(monkeypatch):
    monkeypatch.setattr(system_mod, "_PYCAW_AVAILABLE", False)
    result = _agent().process(_msg("volume_control", {"direction": "up"}))
    assert result["status"] == "success"
    assert "en desarrollo" in result["data"]["result"]
    assert result["data"]["enabled"] is False


def test_volumen_direccion_desde_texto(monkeypatch):
    monkeypatch.setattr(system_mod, "_PYCAW_AVAILABLE", True)
    agent = _agent()
    monkeypatch.setattr(agent, "_set_volume_pycaw", lambda d: (d == "down"))
    result = agent.process(_msg("volume_control", text="baja el volumen"))
    assert result["data"]["enabled"] is True
    assert result["data"]["direction"] == "down"


# ────────── Papelera ──────────

def test_vaciar_papelera(monkeypatch):
    calls = []
    def fake_run(args, capture_output=False, text=False, timeout=None):
        calls.append(args)
        return None
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _agent().process(_msg("empty_trash"))
    assert result["status"] == "success"
    assert "Clear-RecycleBin" in " ".join(calls[0])


# ────────── Procesos ──────────

class _FakeTasklist:
    stdout = (
        "Header1\nHeader2\nHeader3\n"
        "chrome.exe   1234 Console\npython.exe   5678 Console\n"
    )


def test_listar_procesos(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeTasklist())
    agent = _agent()
    processes = agent.list_processes()
    assert processes and processes[0]["name"] == "chrome.exe"


def test_matar_proceso(monkeypatch):
    calls = []
    def fake_run(args, capture_output=False, text=False, timeout=None):
        calls.append(args)
        return None
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _agent().process(_msg("manage_processes", text="mata a chrome"))
    assert result["status"] == "success"
    assert any("taskkill" in a for a in calls)


# ────────── Fallback ──────────

def test_intencion_no_soportada():
    result = _agent().process(_msg("intencion_futura"))
    assert result["status"] == "success"
    assert "en desarrollo" in result["data"]["result"]
