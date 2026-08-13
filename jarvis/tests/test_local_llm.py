"""
test_local_llm.py - SEMANA 8, FASE 4: LLM local opcional

Cubre la cadena de fallback Ollama → Gemini → plantillas del wrapper
LocalLLM (inyectable, sin red) y su integración en el orquestador
para enriquecer respuestas de intenciones no implementadas.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brain.local_llm as llm_mod
from brain.local_llm import LocalLLM
from orchestrator.orchestrator import JarvisState, Orchestrator


# ==================== CADENA DE PROVEEDORES ====================

def test_primer_proveedor_gana():
    llm = LocalLLM(providers=[
        ("a", lambda p, s: "respuesta A"),
        ("b", lambda p, s: "respuesta B"),
    ])
    result = llm.generate("hola")
    assert result["text"] == "respuesta A"
    assert result["provider"] == "a"


def test_cae_al_segundo_si_primero_falla():
    llm = LocalLLM(providers=[
        ("a", lambda p, s: None),
        ("b", lambda p, s: "respuesta B"),
    ])
    result = llm.generate("hola")
    assert result["provider"] == "b"
    assert llm.get_last_provider() == "b"


def test_todos_none_devuelve_none():
    llm = LocalLLM(providers=[
        ("a", lambda p, s: None),
        ("b", lambda p, s: ""),
    ])
    result = llm.generate("hola")
    assert result["text"] is None
    assert result["provider"] is None


def test_provider_que_lanza_excepcion_degrada():
    def boom(p, s):
        raise RuntimeError("cayó el proveedor")

    llm = LocalLLM(providers=[
        ("boom", boom),
        ("ok", lambda p, s: "sobreviví"),
    ])
    result = llm.generate("hola")
    assert result["provider"] == "ok"


def test_generate_text():
    llm = LocalLLM(providers=[("a", lambda p, s: "texto")])
    assert llm.generate_text("p") == "texto"
    llm2 = LocalLLM(providers=[("a", lambda p, s: None)])
    assert llm2.generate_text("p") is None


def test_plantillas_ultimo_recurso():
    llm = LocalLLM(providers=[
        ("ollama", lambda p, s: None),
        ("gemini", lambda p, s: None),
        ("templates", lambda p, s: llm_mod.LocalLLM._templates_chat(p, s)),
    ])
    result = llm.generate("¿cómo estás?")
    assert result["provider"] == "templates"
    assert "No hay LLM local" in result["text"]


def test_ollama_chat_con_requests_fake(monkeypatch):
    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"response": "Respuesta de Ollama", "done": True}

    calls = {}

    def fake_post(url, json=None, timeout=None):
        calls["url"] = url
        calls["body"] = json
        return FakeResp()

    monkeypatch.setattr(llm_mod, "_requests", types.SimpleNamespace(post=fake_post))
    monkeypatch.setattr(llm_mod, "_REQUESTS_AVAILABLE", True)
    llm = LocalLLM(model="llama3.2", providers=[("ollama", None)])
    # Re-empaquetamos con el callable real tras el monkeypatch.
    llm._providers = [("ollama", llm._ollama_chat)]
    result = llm.generate("hola")
    assert result["provider"] == "ollama"
    assert calls["body"]["model"] == "llama3.2"
    assert calls["body"]["stream"] is False


def test_ollama_chat_sin_requests():
    llm = LocalLLM(providers=[("ollama", llm_mod.LocalLLM._ollama_chat)])
    result = llm.generate("hola")
    # Sin requests o sin servidor → degrada (None), nunca lanza.
    assert result["text"] is None or result["provider"] != "ollama"


def test_available_ollama(monkeypatch):
    llm = LocalLLM()
    monkeypatch.setattr(llm, "_ollama_reachable", lambda: True)
    assert llm.available() is True


def test_available_solo_gemini(monkeypatch):
    llm = LocalLLM(api_key="fake-key")
    monkeypatch.setattr(llm, "_ollama_reachable", lambda: False)
    monkeypatch.setattr(llm_mod, "_GENAI_AVAILABLE", True)
    assert llm.available() is True
    monkeypatch.setattr(llm_mod, "_GENAI_AVAILABLE", False)
    assert llm.available() is False


def test_gemini_requires_key():
    llm = LocalLLM()  # sin key
    assert llm._gemini_enabled() is False
    llm2 = LocalLLM(api_key="fake")
    monkeypatched = bool(llm_mod._GENAI_AVAILABLE and llm2._api_key)
    assert llm2._gemini_enabled() == monkeypatched


def test_get_status():
    llm = LocalLLM(providers=[("a", lambda p, s: "x")])
    llm.generate("hola")
    status = llm.get_status()
    assert status["last_provider"] == "a"
    assert status["calls"] == 1
    assert status["providers"] == ["a"]


# ==================== INTEGRACIÓN EN EL ORQUESTADOR ====================

class _FakeLLM:
    def __init__(self, available=True, text="Puedo ayudarte con el clima."):
        self._available = available
        self._text = text

    def available(self):
        return self._available

    def generate_text(self, prompt, system=None):
        return self._text


def _stub(llm):
    inst = object.__new__(Orchestrator)
    inst.config = types.SimpleNamespace(
        base_dir=".",
        data_dir="data",
        system=types.SimpleNamespace(name="Jarvis", version="0.1.0"),
    )
    spoken = []
    inst.speak = lambda text: spoken.append(text)
    inst._publish = lambda *a, **k: None
    inst.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    inst.engine = None
    inst._voice_available = False
    inst.is_running = True
    inst.state = JarvisState.IDLE
    inst.agent_registry = None
    inst.decision_engine = None
    inst.error_handler = None
    inst.local_llm = llm
    inst._spoken = spoken
    return inst


def _intent(name="holograma", confidence=0.9):
    return types.SimpleNamespace(name=name, confidence=confidence, parameters={},
                                 raw_text=name)


def test_execute_intent_enriquece_con_llm():
    inst = _stub(_FakeLLM(available=True))
    resp = inst._execute_intent(_intent("holograma"), "haz un holograma")
    assert "no tengo implementada" in resp
    assert "Puedo ayudarte con el clima" in resp


def test_execute_intent_sin_llm_mantiene_mensaje():
    inst = _stub(_FakeLLM(available=False))
    resp = inst._execute_intent(_intent("holograma"), "haz un holograma")
    assert "no tengo implementada" in resp
    assert "Puedo ayudarte" not in resp


def test_execute_intent_sin_local_llm():
    inst = _stub(None)
    resp = inst._execute_intent(_intent("holograma"), "haz un holograma")
    assert "no tengo implementada" in resp
