"""
test_dialog_agent.py - Tests del Dialog Agent (SEMANA 5, FASE 3)

Gemini, pyjokes y MyMemory están mockeados: ninguna prueba hace
llamadas externas reales.
"""

import agents.dialog as dialog_module
from agents.base import AgentBase
from agents.dialog import DialogAgent


# ==================== DOBLES DE PRUEBA ====================

class _FakeModel:
    def __init__(self):
        self.prompts = []
        self.fail = False

    def generate_content(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("API error")
        return _FakeResponse()


class _FakeResponse:
    text = "Respuesta de prueba de JARVIS"


class _FakeGenai:
    def __init__(self):
        self.configured_key = None
        self.model = _FakeModel()
        self.model_names = []

    def configure(self, **kwargs):
        self.configured_key = kwargs.get("api_key")

    def GenerativeModel(self, name):
        self.model_names.append(name)
        return self.model


class _FakePyjokes:
    def get_joke(self, language="en", category="neutral"):
        return "Chiste de prueba en espanol"


class _FakeTranslateResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeMyMemory:
    def get(self, url, params=None, timeout=None):
        return _FakeTranslateResponse({
            "responseData": {"translatedText": "Hello"},
        })


def _agent(tmp_path, with_gemini=False):
    config = {"assistant_name_file": str(tmp_path / "assistant_name.txt")}
    if with_gemini:
        config["gemini_api_key"] = "fake-key"
    return DialogAgent("dialog_agent", config)


def _enable_gemini(monkeypatch, fake=None):
    fake = fake or _FakeGenai()
    monkeypatch.setattr(dialog_module, "genai", fake)
    monkeypatch.setattr(dialog_module, "_GENAI_AVAILABLE", True)
    return fake


def _enable_pyjokes(monkeypatch, fake=None):
    fake = fake or _FakePyjokes()
    monkeypatch.setattr(dialog_module, "pyjokes", fake)
    monkeypatch.setattr(dialog_module, "_PYJOKES_AVAILABLE", True)
    return fake


def _enable_mymemory(monkeypatch):
    monkeypatch.setattr(dialog_module, "requests", _FakeMyMemory())
    monkeypatch.setattr(dialog_module, "_REQUESTS_AVAILABLE", True)


def _process(agent, intent, params=None, text=""):
    return agent.process({
        "intent": intent,
        "parameters": params or {},
        "text": text,
    })


# ==================== ESTRUCTURA Y CONTRATO ====================

def test_hereda_de_agentbase():
    assert isinstance(DialogAgent("dialog_agent", {}), AgentBase)


def test_mensaje_invalido():
    resp = DialogAgent("dialog_agent", {}).process("hola")
    assert resp["status"] == "error"
    assert resp["agent"] == "dialog_agent"
    assert "Mensaje inv" in resp["data"]["result"]


def test_intencion_no_soportada():
    resp = _process(DialogAgent("dialog_agent", {}), "hack_the_pentagon")
    assert "en desarrollo" in resp["data"]["result"]


# ==================== CHISTES ====================

def test_tell_joke_pyjokes(monkeypatch, tmp_path):
    _enable_pyjokes(monkeypatch)
    resp = _process(_agent(tmp_path), "tell_joke")
    assert resp["status"] == "success"
    assert resp["data"]["source"] == "pyjokes"
    assert resp["data"]["result"]


def test_tell_joke_sin_pyjokes(monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_module, "_PYJOKES_AVAILABLE", False)
    resp = _process(_agent(tmp_path), "tell_joke")
    assert resp["data"]["source"] == "templates"
    assert resp["data"]["result"]


def test_tell_joke_gemini(monkeypatch, tmp_path):
    fake = _enable_gemini(monkeypatch)
    resp = _process(_agent(tmp_path, with_gemini=True), "tell_joke")
    assert resp["data"]["source"] == "gemini"
    assert resp["data"]["result"] == "Respuesta de prueba de JARVIS"
    assert fake.configured_key == "fake-key"


def test_tell_joke_gemini_falla(monkeypatch, tmp_path):
    fake = _enable_gemini(monkeypatch)
    fake.model.fail = True
    _enable_pyjokes(monkeypatch)
    resp = _process(_agent(tmp_path, with_gemini=True), "tell_joke")
    assert resp["status"] == "success"
    assert resp["data"]["source"] == "pyjokes"


def test_gemini_desactivado_sin_key(monkeypatch, tmp_path):
    _enable_gemini(monkeypatch)
    _enable_pyjokes(monkeypatch)
    resp = _process(_agent(tmp_path), "tell_joke")
    assert resp["data"]["source"] == "pyjokes"


# ==================== CAMBIO DE NOMBRE ====================

def test_change_name_params(tmp_path):
    agent = _agent(tmp_path)
    resp = _process(agent, "change_name", {"new_name": "Nova"})
    assert "Nova" in resp["data"]["result"]
    assert resp["data"]["source"] == "file"
    name_file = tmp_path / "assistant_name.txt"
    assert name_file.read_text(encoding="utf-8") == "Nova"


def test_change_name_desde_texto(tmp_path):
    resp = _process(_agent(tmp_path), "change_name", text="cambiate el nombre a pepe")
    assert "Pepe" in resp["data"]["result"]


def test_change_name_sin_nombre(tmp_path):
    resp = _process(_agent(tmp_path), "change_name")
    assert "quieres que me llame" in resp["data"]["result"]


def test_nombre_persistido(tmp_path):
    _agent(tmp_path).process({
        "intent": "change_name",
        "parameters": {"new_name": "Nova"},
        "text": "",
    })
    nuevo = _agent(tmp_path)
    assert nuevo._assistant_name == "Nova"


# ==================== AYUDA ====================

def test_help_query_desde_catalogo(tmp_path):
    from brain.intent_data import INTENT_CATALOG
    resp = _process(_agent(tmp_path), "help_query")
    assert resp["data"]["source"] == "templates"
    assert "Esto es lo que puedo hacer" in resp["data"]["result"]
    assert resp["data"]["count"] == len(INTENT_CATALOG)
    assert "comando:" in resp["data"]["result"]


# ==================== SMALLTALK ====================

def test_smalltalk_saludo(tmp_path):
    resp = _process(_agent(tmp_path), "smalltalk", text="hola")
    assert resp["data"]["source"] == "templates"
    assert "puedo ayudarte" in resp["data"]["result"]


def test_smalltalk_como_estas(tmp_path):
    resp = _process(_agent(tmp_path), "smalltalk", text="como estas")
    assert "listo para ayudarte" in resp["data"]["result"]


def test_smalltalk_quien_eres(tmp_path):
    resp = _process(_agent(tmp_path), "smalltalk", text="quien eres")
    assert "JARVIS" in resp["data"]["result"]


def test_smalltalk_gemini(monkeypatch, tmp_path):
    _enable_gemini(monkeypatch)
    resp = _process(_agent(tmp_path, with_gemini=True), "smalltalk", text="hola")
    assert resp["data"]["source"] == "gemini"


def test_smalltalk_gemini_falla(monkeypatch, tmp_path):
    fake = _enable_gemini(monkeypatch)
    fake.model.fail = True
    resp = _process(_agent(tmp_path, with_gemini=True), "smalltalk", text="hola")
    assert resp["data"]["source"] == "templates"


def test_smalltalk_sin_texto(tmp_path):
    resp = _process(_agent(tmp_path), "smalltalk")
    assert "Dime algo" in resp["data"]["result"]


def test_smalltalk_me_llamo(tmp_path):
    resp = _process(_agent(tmp_path), "smalltalk", text="me llamo nova")
    assert "Nova" in resp["data"]["result"]


# ==================== CONTEXTO DE SESIÓN ====================

def test_contexto_sesion(monkeypatch, tmp_path):
    fake = _enable_gemini(monkeypatch)
    agent = _agent(tmp_path, with_gemini=True)
    _process(agent, "smalltalk", text="Primera frase de la sesion")
    _process(agent, "smalltalk", text="Segunda frase de la sesion")
    segundo_prompt = fake.model.prompts[1]
    assert "Primera frase de la sesion" in segundo_prompt
    assert "JARVIS: Respuesta de prueba de JARVIS" in segundo_prompt


def test_historial_limitado(monkeypatch, tmp_path):
    _enable_gemini(monkeypatch)
    agent = _agent(tmp_path, with_gemini=True)
    for i in range(6):
        _process(agent, "smalltalk", text=f"frase {i}")
    assert len(agent._history) <= 10


# ==================== TRADUCCIÓN ====================

def test_translate_mymemory(monkeypatch, tmp_path):
    _enable_mymemory(monkeypatch)
    resp = _process(
        _agent(tmp_path),
        "translate_text",
        {"text": "hola", "source_lang": "es", "target_lang": "en"},
    )
    assert resp["data"]["source"] == "mymemory"
    assert resp["data"]["result"] == "Hello"


def test_translate_desde_texto(monkeypatch, tmp_path):
    _enable_mymemory(monkeypatch)
    resp = _process(_agent(tmp_path), "translate_text", text="traduce hola al ingles")
    assert resp["data"]["result"] == "Hello"


def test_translate_sin_requests(monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_module, "_REQUESTS_AVAILABLE", False)
    resp = _process(_agent(tmp_path), "translate_text", {"text": "hola"})
    assert "Traducción en desarrollo" == resp["data"]["result"]


def test_translate_sin_texto(tmp_path):
    resp = _process(_agent(tmp_path), "translate_text")
    assert "texto quieres que traduzca" in resp["data"]["result"]
