"""
Tests adicionales de cobertura (SEMANA 5, FASE 5)

Sube la cobertura de system.py y dialog.py por encima del 90% cubriendo
ramas no ejercitadas: parámetros inválidos, errores de handlers, rutas
de texto libre, pycaw con éxito/fallo, papelera/procesos con error y
rutas de extracción de texto del DialogAgent.
"""

import builtins

import agents.dialog as dialog_mod
import agents.system as system_mod
from agents.dialog import DialogAgent
from agents.system import SystemAgent


def _agent() -> SystemAgent:
    return SystemAgent()


def _msg(intent, params=None, text=""):
    return {"intent": intent, "parameters": params or {}, "text": text}


# ══════════════════ SYSTEM: ramas de process() ══════════════════

def test_process_params_no_dict(monkeypatch):
    calls = []
    monkeypatch.setattr(system_mod.os, "system", lambda c: calls.append(c))
    result = _agent().process(
        {"intent": "system_control", "parameters": "oops", "text": "apaga el equipo"}
    )
    assert result["status"] == "success"
    assert calls


def test_process_handler_error(monkeypatch):
    agent = _agent()

    def boom(params, user_input):
        raise RuntimeError("boom")

    agent._handlers["system_control"] = boom
    result = agent.process(_msg("system_control", {"action": "apagar"}))
    assert result["status"] == "error"
    assert agent.has_errors() is True
    assert "boom" in result["data"]["error"]


def test_handle_event():
    _agent().handle_event({"type": "test"})


# ══════════════════ SYSTEM: apertura por texto libre ══════════════════

def test_abrir_app_por_texto(monkeypatch):
    opened = []
    monkeypatch.setattr(
        system_mod.webbrowser, "open", lambda url: opened.append(url)
    )
    result = _agent().process(_msg("open_application", text="abre youtube"))
    assert result["status"] == "success"
    assert opened and "youtube.com" in opened[0]
    assert "youtube" in result["data"]["result"]


def test_abrir_app_sin_app_sin_texto():
    result = _agent().process(_msg("open_application"))
    assert result["data"]["result"] == "¿Qué aplicación quieres que abra?"


def test_abrir_carpeta_por_texto(monkeypatch):
    started = []
    monkeypatch.setattr(system_mod.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(system_mod.os, "startfile", lambda p: started.append(p))
    result = _agent().process(
        {"intent": "open_folder", "text": "abre la carpeta documentos"}
    )
    assert result["status"] == "success"
    assert started and started[0] == "documentos"


def test_abrir_carpeta_sin_carpeta():
    result = _agent().process(_msg("open_folder"))
    assert result["data"]["result"] == "¿Qué carpeta quieres abrir?"


def test_strip_query():
    query = SystemAgent._strip_query(
        "abre la carpeta documentos", ["abre la carpeta", "abre", "carpeta"]
    )
    assert query == "documentos"


# ══════════════════ SYSTEM: volumen con pycaw ══════════════════

class _FakeVolume:
    def QueryInterface(self, iid):
        return self

    def SetMute(self, value, ctx):
        pass

    def GetMasterVolumeLevelScalar(self):
        return 0.5

    def SetMasterVolumeLevelScalar(self, value, ctx):
        pass


class _FakeAudioEndpointVolume:
    _iid_ = "fake-iid"


class _FakeDevices:
    def Activate(self, iid, a, b):
        return _FakeVolume()


class _FakeAudioUtilities:
    @staticmethod
    def GetSpeakers():
        return _FakeDevices()


def test_volumen_pycaw_ok(monkeypatch):
    monkeypatch.setattr(system_mod, "_PYCAW_AVAILABLE", True)
    monkeypatch.setattr(system_mod, "AudioUtilities", _FakeAudioUtilities)
    monkeypatch.setattr(
        system_mod, "IAudioEndpointVolume", _FakeAudioEndpointVolume
    )
    agent = _agent()
    up = agent.process(_msg("volume_control", {"direction": "up"}))
    assert up["data"]["enabled"] is True
    assert up["data"]["direction"] == "up"
    mute = agent.process(_msg("volume_control", {"direction": "mute"}))
    assert mute["data"]["enabled"] is True
    assert mute["data"]["direction"] == "mute"


def test_volumen_pycaw_error(monkeypatch):
    class _Boom:
        @staticmethod
        def GetSpeakers():
            raise RuntimeError("comtypes no responde")

    monkeypatch.setattr(system_mod, "_PYCAW_AVAILABLE", True)
    monkeypatch.setattr(system_mod, "AudioUtilities", _Boom)
    monkeypatch.setattr(
        system_mod, "IAudioEndpointVolume", _FakeAudioEndpointVolume
    )
    agent = _agent()
    result = agent.process(_msg("volume_control", {"direction": "up"}))
    assert result["data"]["enabled"] is False
    assert agent.has_errors() is True


def test_volumen_set_pycaw_devuelve_false(monkeypatch):
    monkeypatch.setattr(system_mod, "_PYCAW_AVAILABLE", True)
    agent = _agent()
    monkeypatch.setattr(agent, "_set_volume_pycaw", lambda d: False)
    result = agent.process(_msg("volume_control", {"direction": "up"}))
    assert "no se pudo ajustar" in result["data"]["result"]
    assert result["data"]["enabled"] is False


def test_detectar_direccion_volumen():
    assert SystemAgent._detect_volume_direction("silenciar el volumen") == "mute"
    assert SystemAgent._detect_volume_direction("sube el volumen") == "up"
    assert SystemAgent._detect_volume_direction("baja el volumen") == "down"
    assert SystemAgent._detect_volume_direction("volumen aleatorio") == "up"


# ══════════════════ SYSTEM: papelera y procesos con error ══════════════════

def test_vaciar_papelera_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("powershell no disponible")

    monkeypatch.setattr(system_mod.subprocess, "run", fake_run)
    result = _agent().process(_msg("empty_trash"))
    assert result["data"]["result"] == "No se pudo vaciar la papelera"


def test_listar_procesos_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("tasklist no disponible")

    monkeypatch.setattr(system_mod.subprocess, "run", fake_run)
    assert _agent().list_processes() == []


class _FakeTasklistLargo:
    stdout = "H1\nH2\nH3\n" + "".join(
        f"proceso_{i}.exe   {1000 + i} Console\n" for i in range(5)
    )


def test_listar_procesos_limite(monkeypatch):
    monkeypatch.setattr(
        system_mod.subprocess, "run", lambda *a, **k: _FakeTasklistLargo()
    )
    processes = _agent().list_processes(limit=2)
    assert len(processes) == 2


def test_matar_proceso_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("taskkill falló")

    monkeypatch.setattr(system_mod.subprocess, "run", fake_run)
    agent = _agent()
    result = agent.process(_msg("manage_processes", text="mata a chrome.exe"))
    assert "No se pudo terminar" in result["data"]["result"]
    assert agent.has_errors() is True


def test_matar_sin_nombre():
    result = _agent().process(_msg("manage_processes", text="mata a"))
    assert result["data"]["result"] == "¿Qué proceso quieres terminar?"


def test_gestion_procesos_lista(monkeypatch):
    monkeypatch.setattr(
        system_mod.subprocess, "run", lambda *a, **k: _FakeTasklistLargo()
    )
    result = _agent().process(_msg("manage_processes", text="lista los procesos"))
    assert result["data"]["result"] == "Procesos activos"
    assert result["data"]["processes"]


# ══════════════════ DIALOG: ramas de process() ══════════════════

def test_dialog_params_no_dict():
    result = DialogAgent().process({"intent": "tell_joke", "parameters": "oops"})
    assert result["status"] == "success"


def test_dialog_handler_error():
    agent = DialogAgent()

    def boom(params, user_input):
        raise RuntimeError("boom")

    agent._handlers["tell_joke"] = boom
    result = agent.process({"intent": "tell_joke"})
    assert result["status"] == "error"
    assert agent.has_errors() is True


def test_dialog_handle_event():
    DialogAgent().handle_event({"type": "test"})


# ══════════════════ DIALOG: modo Gemini ══════════════════

def test_gemini_create_model_none(monkeypatch):
    agent = DialogAgent()
    agent._api_key = "clave"
    monkeypatch.setattr(agent, "_create_model", lambda: None)
    monkeypatch.setattr(dialog_mod.genai, "configure", lambda **kwargs: None)
    result = agent._with_gemini(
        "tell_joke", {}, "", lambda: {"result": "fallback"}
    )
    assert result["result"] == "fallback"


def test_create_model_loop_exhausted(monkeypatch):
    class _FakeGenai:
        @staticmethod
        def GenerativeModel(name):
            raise Exception("modelo no disponible")

    monkeypatch.setattr(dialog_mod, "genai", _FakeGenai)
    monkeypatch.setattr(dialog_mod, "_MODEL_NAMES", ("gemini-xyz",))
    assert DialogAgent()._create_model() is None


def test_gemini_falla_usa_fallback(monkeypatch):
    class _Model:
        def generate_content(self, prompt):
            raise RuntimeError("API falla")

    agent = DialogAgent()
    agent._api_key = "clave"
    agent._model = _Model()
    result = agent._with_gemini(
        "tell_joke", {}, "hola", lambda: {"result": "fallback"}
    )
    assert result["result"] == "fallback"
    assert agent.has_errors() is True


# ══════════════════ DIALOG: chistes y nombre ══════════════════

def test_template_joke_error(monkeypatch):
    def boom():
        raise RuntimeError("pyjokes falla")

    monkeypatch.setattr(dialog_mod.pyjokes, "get_joke", boom)
    result = DialogAgent()._template_joke()
    assert "jardinero" in result["result"]
    assert result["source"] == "templates"


def test_extract_name_ultima_palabra():
    assert DialogAgent._extract_name("quiero llamarte JARVIS") == "JARVIS"


def test_extract_name_vacio():
    assert DialogAgent._extract_name("") == ""


def test_first_word_vacio():
    assert DialogAgent._first_word("") == ""


def test_load_name_error(monkeypatch):
    monkeypatch.setattr(dialog_mod.os.path, "isfile", lambda p: True)

    def fake_open(*args, **kwargs):
        raise OSError("lectura fallida")

    monkeypatch.setattr(builtins, "open", fake_open)
    assert DialogAgent()._load_name() == "JARVIS"


def test_save_name_error(monkeypatch):
    def fake_makedirs(*args, **kwargs):
        raise OSError("sin espacio en disco")

    monkeypatch.setattr(dialog_mod.os, "makedirs", fake_makedirs)
    agent = DialogAgent()
    assert agent._save_name("JARVIS2") == "memory"
    assert agent.has_errors() is True


# ══════════════════ DIALOG: ayuda y smalltalk ══════════════════

def test_build_help_catalogo_vacio(monkeypatch):
    monkeypatch.setattr(dialog_mod, "INTENT_CATALOG", {})
    result = DialogAgent()._build_help()
    assert result["count"] == 0
    assert "No tengo catálogo" in result["result"]


def test_smalltalk_ayuda():
    result = DialogAgent().process(
        {"intent": "smalltalk", "text": "qué puedes hacer"}
    )
    assert "puedo hacer" in result["data"]["result"]


def test_smalltalk_sin_regla():
    result = DialogAgent().process(
        {"intent": "smalltalk", "text": "blah blah xyz sin sentido"}
    )
    assert "No estoy seguro" in result["data"]["result"]


# ══════════════════ DIALOG: traducción y HTTP ══════════════════

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeRequests:
    def __init__(self, payload=None):
        self._payload = payload

    def get(self, url, params=None, timeout=None, headers=None):
        return _FakeResp(self._payload or {})


def test_translate_sin_traduccion(monkeypatch):
    monkeypatch.setattr(dialog_mod, "requests", _FakeRequests({}))
    result = DialogAgent().process(
        {"intent": "translate_text", "text": "traduce hola"}
    )
    assert "en desarrollo" in result["data"]["result"]


def test_extract_translation_text_translate():
    assert DialogAgent._extract_translation_text("translate hola") == "hola"


def test_get_json_error(monkeypatch):
    class _RequestsRotos:
        @staticmethod
        def get(url, params=None, timeout=None, headers=None):
            raise ConnectionError("sin red")

    monkeypatch.setattr(dialog_mod, "requests", _RequestsRotos)
    agent = DialogAgent()
    assert agent._get_json("https://api.mymemory.translated.net/get") is None
    assert agent.has_errors() is True
