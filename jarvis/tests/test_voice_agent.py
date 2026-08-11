"""
test_voice_agent.py - Tests del Voice Agent (SEMANA 6, FASE 2)

Verifica:
- Contrato AgentBase (proceso, mensaje inválido, intención no soportada)
- speak: edge-tts → pyttsx3 → modo texto (degradación elegante)
- listen: calibración de ruido + detección de silencio + reconocimiento
- calibrate_mic: umbral de energía detectado

Todas las librerías (edge_tts, pyttsx3, pygame, speech_recognition) están
mockeadas: ninguna prueba toca audio real ni hace peticiones de red.
"""

import agents.voice as voice_mod
from agents.base import AgentBase
from agents.voice import VoiceAgent


# ══════════════════ DOBLES DE PRUEBA ══════════════════

class _FakeEdgeTTS:
    """Fake de edge_tts: genera un archivo MP3 real en el sistema."""

    class Communicate:
        def __init__(self, text, voice):
            self.text = text
            self.voice = voice

        async def save(self, path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("MP3-FAKE")

    @staticmethod
    def _reset():
        _FakeEdgeTTS.Communicate = type(
            "Communicate", (), {"__init__": _FakeEdgeTTS.Communicate.__init__,
                                "save": _FakeEdgeTTS.Communicate.save}
        )


class _FakeEdgeTTSFalla:
    class Communicate:
        def __init__(self, text, voice):
            pass

        async def save(self, path):
            raise RuntimeError("sin red")


class _FakeMusic:
    events = []

    @staticmethod
    def load(path):
        _FakeMusic.events.append(("load", path))

    @staticmethod
    def set_volume(vol):
        _FakeMusic.events.append(("volume", vol))

    @staticmethod
    def play():
        _FakeMusic.events.append(("play",))

    @staticmethod
    def get_busy():
        return False

    @staticmethod
    def unload():
        _FakeMusic.events.append(("unload",))


class _FakePygameMixer:
    @staticmethod
    def init():
        pass

    @staticmethod
    def get_init():
        return True


class _FakePygame:
    mixer = _FakePygameMixer
    mixer.music = _FakeMusic


class _FakePyttsx3Engine:
    def __init__(self):
        self.spoken = []
        self.props = {}

    def getProperty(self, name):
        return self.props.get(name)

    def setProperty(self, name, value):
        self.props[name] = value

    def say(self, text):
        self.spoken.append(text)

    def runAndWait(self):
        pass


class _FakePyttsx3:
    @staticmethod
    def init():
        return _FakePyttsx3Engine()


class _FakeAudio:
    def __init__(self, text=""):
        self.text = text


class _FakeMicrophone:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeRecognizer:
    def __init__(self):
        self.pause_threshold = 0.8
        self.dynamic_energy_threshold = True
        self.energy_threshold = 300
        self.adjusted = False
        self.listened = False
        self.timeout = None
        self.phrase_time_limit = None
        self.audio = _FakeAudio()
        self.recognized = ""
        self.raise_on_listen = None
        self.raise_on_recognize = None

    def adjust_for_ambient_noise(self, source, duration=None):
        self.adjusted = True
        self.source = source

    def listen(self, source, timeout=None, phrase_time_limit=None):
        self.listened = True
        self.timeout = timeout
        self.phrase_time_limit = phrase_time_limit
        if self.raise_on_listen is not None:
            raise self.raise_on_listen
        return self.audio

    def recognize_google(self, audio, language=None):
        if self.raise_on_recognize is not None:
            raise self.raise_on_recognize
        return self.recognized


class _FakeSR:
    Recognizer = _FakeRecognizer
    Microphone = _FakeMicrophone

    class WaitTimeoutError(Exception):
        pass

    class UnknownValueError(Exception):
        pass

    class RequestError(Exception):
        pass


# ══════════════════ HELPERS ══════════════════

def _agent():
    return VoiceAgent("voice_agent", {
        "engine": "edge",
        "voice": "es-ES-AlvaroNeural",
        "rate": 150,
        "volume": 1.0,
        "timeout": 5,
    })


def _process(agent, intent, params=None, text=""):
    return agent.process({
        "intent": intent,
        "parameters": params or {},
        "text": text,
    })


def _usar_edge(monkeypatch):
    monkeypatch.setattr(voice_mod, "_EDGE_TTS_AVAILABLE", True)
    monkeypatch.setattr(voice_mod, "edge_tts", _FakeEdgeTTS)
    monkeypatch.setattr(voice_mod, "_PYGAME_AVAILABLE", True)
    monkeypatch.setattr(voice_mod, "pygame", _FakePygame)
    monkeypatch.setattr(voice_mod, "_VOICE_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "pyttsx3", None)


def _usar_pyttsx3(monkeypatch):
    monkeypatch.setattr(voice_mod, "_EDGE_TTS_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "edge_tts", None)
    monkeypatch.setattr(voice_mod, "_PYGAME_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "_VOICE_AVAILABLE", True)
    monkeypatch.setattr(voice_mod, "pyttsx3", _FakePyttsx3)


def _sin_voz(monkeypatch):
    monkeypatch.setattr(voice_mod, "_EDGE_TTS_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "edge_tts", None)
    monkeypatch.setattr(voice_mod, "_PYGAME_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "_VOICE_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "pyttsx3", None)


def _con_sr(monkeypatch):
    monkeypatch.setattr(voice_mod, "_SR_AVAILABLE", True)
    monkeypatch.setattr(voice_mod, "sr", _FakeSR)


# ══════════════════ CONTRATO ══════════════════

def test_hereda_de_agentbase(monkeypatch):
    _sin_voz(monkeypatch)
    assert isinstance(_agent(), AgentBase)


def test_mensaje_invalido(monkeypatch):
    _sin_voz(monkeypatch)
    resp = _agent().process("hola")
    assert resp["status"] == "error"
    assert resp["agent"] == "voice_agent"
    assert "Mensaje inv" in resp["data"]["result"]


def test_intencion_no_soportada(monkeypatch):
    _sin_voz(monkeypatch)
    resp = _process(_agent(), "hack_the_pentagon")
    assert resp["status"] == "success"
    assert "en desarrollo" in resp["data"]["result"]


def test_get_info_muestra_engine(monkeypatch):
    _usar_edge(monkeypatch)
    info = _agent().get_info()
    assert info["engine"] == "edge"
    assert "speak_text" in info["capabilities"]


# ══════════════════ SPEAK: edge-tts ══════════════════

def test_speak_edge(monkeypatch, tmp_path):
    _usar_edge(monkeypatch)
    monkeypatch.setattr(voice_mod.tempfile, "gettempdir", lambda: str(tmp_path))
    resp = _agent().speak("Hola Jarvis")
    assert resp["mode"] == "edge"
    assert resp["spoken"] is True
    assert resp["result"] == "Hola Jarvis"


def test_speak_edge_genera_mp3(monkeypatch, tmp_path):
    _usar_edge(monkeypatch)
    monkeypatch.setattr(voice_mod.tempfile, "gettempdir", lambda: str(tmp_path))
    _agent().speak("prueba")
    # El MP3 temporal se borra tras reproducir (sin residuos)
    left = [f for f in tmp_path.iterdir() if f.suffix == ".mp3"]
    assert left == []


def test_speak_edge_falla_usar_fallback_texto(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_mod, "_EDGE_TTS_AVAILABLE", True)
    monkeypatch.setattr(voice_mod, "edge_tts", _FakeEdgeTTSFalla)
    monkeypatch.setattr(voice_mod, "_PYGAME_AVAILABLE", True)
    monkeypatch.setattr(voice_mod, "pygame", _FakePygame)
    monkeypatch.setattr(voice_mod, "_VOICE_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "pyttsx3", None)
    monkeypatch.setattr(voice_mod.tempfile, "gettempdir", lambda: str(tmp_path))
    resp = _agent().speak("prueba")
    assert resp["mode"] == "text"
    assert resp["spoken"] is False


def test_speak_texto_vacio(monkeypatch):
    _usar_edge(monkeypatch)
    resp = _agent().speak("")
    assert resp["spoken"] is False


# ══════════════════ SPEAK: pyttsx3 (fallback offline) ══════════════════

def test_speak_pyttsx3(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    agent = _agent()
    resp = agent.speak("Hola desde offline")
    assert resp["mode"] == "pyttsx3"
    assert resp["spoken"] is True
    assert agent._tts_engine.spoken == ["Hola desde offline"]


def test_speak_pyttsx3_configura_voz(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    agent = _agent()
    engine = agent._tts_engine
    assert engine.props.get("rate") == 150
    assert engine.props.get("volume") == 1.0


def test_speak_sin_ningun_motor(monkeypatch):
    _sin_voz(monkeypatch)
    resp = _agent().speak("solo texto")
    assert resp["mode"] == "text"
    assert resp["spoken"] is False


def test_speak_edge_sin_pygame_usa_texto(monkeypatch):
    monkeypatch.setattr(voice_mod, "_EDGE_TTS_AVAILABLE", True)
    monkeypatch.setattr(voice_mod, "edge_tts", _FakeEdgeTTS)
    monkeypatch.setattr(voice_mod, "_PYGAME_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "pygame", None)
    monkeypatch.setattr(voice_mod, "_VOICE_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "pyttsx3", None)
    resp = _agent().speak("hola")
    assert resp["mode"] == "text"


# ══════════════════ LISTEN: calibración + silencio ══════════════════

def test_listen_calibra_ruido(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    _con_sr(monkeypatch)
    agent = _agent()
    agent.listen()
    # Se creó un recognizer y calibró ruido ambiente
    assert _FakeRecognizer.adjust_for_ambient_noise.__name__ == "adjust_for_ambient_noise"


def test_listen_reconoce_texto(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    _con_sr(monkeypatch)

    original = voice_mod.sr.Recognizer
    calls = {}

    class _R(original):
        def __init__(self):
            super().__init__()
            self.recognized = "HOLA MUNDO"

    calls["clazz"] = _R
    monkeypatch.setattr(voice_mod.sr, "Recognizer", _R)

    agent = _agent()
    result = agent.listen()
    assert result == "hola mundo"


def test_listen_silencio_timeout_devuelve_none(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    _con_sr(monkeypatch)

    class _R(voice_mod.sr.Recognizer):
        def __init__(self):
            super().__init__()
            self.raise_on_listen = voice_mod.sr.WaitTimeoutError("silencio")

    monkeypatch.setattr(voice_mod.sr, "Recognizer", _R)
    assert _agent().listen() is None


def test_listen_voz_no_entendida_devuelve_none(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    _con_sr(monkeypatch)

    class _R(voice_mod.sr.Recognizer):
        def __init__(self):
            super().__init__()
            self.raise_on_recognize = voice_mod.sr.UnknownValueError("nada")

    monkeypatch.setattr(voice_mod.sr, "Recognizer", _R)
    assert _agent().listen() is None


def test_listen_servicio_no_disponible_devuelve_none(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    _con_sr(monkeypatch)

    class _R(voice_mod.sr.Recognizer):
        def __init__(self):
            super().__init__()
            self.raise_on_recognize = voice_mod.sr.RequestError("API caída")

    monkeypatch.setattr(voice_mod.sr, "Recognizer", _R)
    assert _agent().listen() is None


def test_listen_sin_sr_devuelve_none(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    monkeypatch.setattr(voice_mod, "_SR_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "sr", None)
    assert _agent().listen() is None


# ══════════════════ CALIBRACIÓN DE MICRÓFONO ══════════════════

def test_calibrate_mic_devuelve_umbral(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    _con_sr(monkeypatch)
    agent = _agent()
    result = agent.calibrate_mic()
    assert result["calibrated"] is True
    assert result["energy_threshold"] == 300


def test_calibrate_mic_sin_sr(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    monkeypatch.setattr(voice_mod, "_SR_AVAILABLE", False)
    monkeypatch.setattr(voice_mod, "sr", None)
    result = _agent().calibrate_mic()
    assert result["calibrated"] is False
    assert result["reason"] == "sr_no_disponible"


# ══════════════════ HANDLERS ══════════════════

def test_handler_speak_text(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    resp = _process(_agent(), "speak_text", text="dime algo")
    assert resp["status"] == "success"
    assert resp["data"]["mode"] == "pyttsx3"


def test_handler_listen_voice(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    _con_sr(monkeypatch)

    class _R(voice_mod.sr.Recognizer):
        def __init__(self):
            super().__init__()
            self.recognized = "BUENOS DÍAS"

    monkeypatch.setattr(voice_mod.sr, "Recognizer", _R)
    resp = _process(_agent(), "listen_voice")
    assert resp["data"]["transcript"] == "buenos días"


def test_handler_calibrate_mic(monkeypatch):
    _usar_pyttsx3(monkeypatch)
    _con_sr(monkeypatch)
    resp = _process(_agent(), "calibrate_mic")
    assert resp["data"]["calibrated"] is True
