"""
test_web_agent.py - Tests del Web Agent (SEMANA 5, FASE 2)

Todas las llamadas HTTP (requests, feedparser, wikipedia) están mockeadas:
ninguna prueba ejecuta peticiones reales a la red.
"""

import agents.web as web_module
from agents.base import AgentBase
from agents.web import WebAgent


# ==================== DOBLES DE PRUEBA ====================

class _FakeResponse:
    def __init__(self, payload, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeRequests:
    def __init__(self, getter):
        self._getter = getter

    def get(self, url, params=None, timeout=None, headers=None):
        return self._getter(url, params, timeout, headers)


class _FakeWikipedia:
    class exceptions:
        class DisambiguationError(Exception):
            pass

        class PageError(Exception):
            pass

    def __init__(self, mode):
        self.mode = mode

    def set_lang(self, lang):
        pass

    def summary(self, query, sentences=2):
        if self.mode == "ok":
            return "La fotosintesis es el proceso por el que las plantas " \
                   "convierten la luz en energia."
        if self.mode == "disambiguation":
            raise self.exceptions.DisambiguationError("varias opciones")
        raise self.exceptions.PageError("sin pagina")


class _FakeFeedparser:
    def __init__(self, titles):
        self._titles = titles

    def parse(self, url):
        return _FakeParsedFeed(self._titles)


class _FakeParsedFeed:
    def __init__(self, titles):
        self.entries = [{"title": t} for t in titles]

    def get(self, key, default=None):
        return self.entries if key == "entries" else default


def _fake_get(url, params=None, timeout=None, headers=None):
    if "geocoding" in url:
        return _FakeResponse({
            "results": [
                {"latitude": -12.04, "longitude": -77.03, "name": "Lima"}
            ]
        })
    if "open-meteo.com" in url:
        return _FakeResponse({
            "current": {
                "temperature_2m": 22.5,
                "relative_humidity_2m": 65,
                "weather_code": 1,
            }
        })
    if "coingecko" in url:
        ids = (params or {}).get("ids", "")
        if ids == "bitcoin":
            return _FakeResponse({
                "bitcoin": {"usd": 65000.0, "usd_24h_change": 2.5}
            })
        return _FakeResponse({
            "ethereum": {"usd": 3500.0, "usd_24h_change": -1.5}
        })
    if "duckduckgo" in url:
        return _FakeResponse(
            {},
            text=(
                '<a rel="nofollow" class="result__a" href="http://x">'
                'Fotosintesis - Wikipedia</a>'
                '<a class="result__snippet" href="#">'
                'La fotosintesis es un proceso quimico.</a>'
            ),
        )
    return _FakeResponse({})


def _mock_http(monkeypatch):
    monkeypatch.setattr(web_module, "requests", _FakeRequests(_fake_get))
    monkeypatch.setattr(web_module, "_REQUESTS_AVAILABLE", True)


def _spy_webbrowser(monkeypatch):
    opened = []
    monkeypatch.setattr(web_module.webbrowser, "open", opened.append)
    return opened


def _agent():
    return WebAgent("web_agent", {})


def _process(agent, intent, params=None, text=""):
    return agent.process({
        "intent": intent,
        "parameters": params or {},
        "text": text,
    })


# ==================== ESTRUCTURA Y CONTRATO ====================

def test_hereda_de_agentbase():
    assert isinstance(_agent(), AgentBase)


def test_mensaje_invalido():
    resp = _agent().process("hola")
    assert resp["status"] == "error"
    assert resp["agent"] == "web_agent"
    assert "Mensaje inv" in resp["data"]["result"]


def test_intencion_no_soportada():
    resp = _process(_agent(), "hack_the_pentagon")
    assert resp["status"] == "success"
    assert "en desarrollo" in resp["data"]["result"]


# ==================== BÚSQUEDA ====================

def test_search_info_wikipedia(monkeypatch):
    monkeypatch.setattr(web_module, "wikipedia", _FakeWikipedia("ok"))
    resp = _process(_agent(), "search_info", {"topic": "fotosintesis"})
    assert resp["status"] == "success"
    assert resp["data"]["source"] == "wikipedia"
    assert "fotosintesis" in resp["data"]["result"]


def test_search_info_disambiguation(monkeypatch):
    monkeypatch.setattr(web_module, "wikipedia", _FakeWikipedia("disambiguation"))
    resp = _process(_agent(), "search_info", {"topic": "python"})
    assert resp["data"]["source"] == "wikipedia"
    assert "Sé más específico" in resp["data"]["result"]


def test_search_info_duckduckgo(monkeypatch):
    monkeypatch.setattr(web_module, "wikipedia", _FakeWikipedia("error"))
    _mock_http(monkeypatch)
    resp = _process(_agent(), "search_info", {"topic": "fotosintesis"})
    assert resp["data"]["source"] == "duckduckgo"
    assert "Fotosintesis" in resp["data"]["result"]


def test_search_info_fallback_google(monkeypatch):
    monkeypatch.setattr(web_module, "wikipedia", None)
    monkeypatch.setattr(web_module, "_WIKIPEDIA_AVAILABLE", False)
    monkeypatch.setattr(web_module, "_REQUESTS_AVAILABLE", False)
    opened = _spy_webbrowser(monkeypatch)
    resp = _process(_agent(), "search_info", {"topic": "fotosintesis"})
    assert resp["data"]["source"] == "google"
    assert "Abriendo la b" in resp["data"]["result"]
    assert opened and "google.com" in opened[0]


def test_search_info_sin_query():
    resp = _process(_agent(), "search_info")
    assert "busque informaci" in resp["data"]["result"]


# ==================== CLIMA ====================

def test_weather_ok(monkeypatch):
    _mock_http(monkeypatch)
    resp = _process(_agent(), "weather_query", {"location": "Lima"})
    assert resp["status"] == "success"
    assert resp["data"]["source"] == "open_meteo"
    assert "Clima en Lima" in resp["data"]["result"]
    assert "22.5" in resp["data"]["result"]
    assert "65%" in resp["data"]["result"]


def test_weather_desde_texto(monkeypatch):
    _mock_http(monkeypatch)
    resp = _process(_agent(), "weather_query", text="clima en Lima")
    assert "Clima en Lima" in resp["data"]["result"]


def test_weather_ciudad_no_encontrada(monkeypatch):
    monkeypatch.setattr(
        web_module,
        "requests",
        _FakeRequests(lambda *a, **k: _FakeResponse({"results": []})),
    )
    monkeypatch.setattr(web_module, "_REQUESTS_AVAILABLE", True)
    resp = _process(_agent(), "weather_query", {"location": "Atlantis"})
    assert "No encontr" in resp["data"]["result"]


def test_weather_sin_requests(monkeypatch):
    monkeypatch.setattr(web_module, "_REQUESTS_AVAILABLE", False)
    opened = _spy_webbrowser(monkeypatch)
    resp = _process(_agent(), "weather_query", {"location": "Lima"})
    assert "Abriendo el clima" in resp["data"]["result"]
    assert opened


def test_weather_sin_lugar():
    resp = _process(_agent(), "weather_query")
    assert "ciudad quieres el clima" in resp["data"]["result"]


# ==================== CRIPTO ====================

def test_crypto_bitcoin(monkeypatch):
    _mock_http(monkeypatch)
    resp = _process(_agent(), "crypto_price", {"coin_name": "bitcoin"})
    assert resp["data"]["source"] == "coingecko"
    assert "bitcoin: 65,000.00 USD" in resp["data"]["result"]
    assert "En 24h" in resp["data"]["result"]


def test_crypto_desde_texto(monkeypatch):
    _mock_http(monkeypatch)
    resp = _process(_agent(), "crypto_price", text="cuanto vale ethereum hoy")
    assert "ethereum: 3,500.00 USD" in resp["data"]["result"]
    assert "1.50%" in resp["data"]["result"]


def test_crypto_no_encontrada(monkeypatch):
    monkeypatch.setattr(
        web_module,
        "requests",
        _FakeRequests(lambda *a, **k: _FakeResponse({})),
    )
    monkeypatch.setattr(web_module, "_REQUESTS_AVAILABLE", True)
    resp = _process(_agent(), "crypto_price", {"coin_name": "bitcoin"})
    assert "No encontr" in resp["data"]["result"]


def test_crypto_sin_requests(monkeypatch):
    monkeypatch.setattr(web_module, "_REQUESTS_AVAILABLE", False)
    opened = _spy_webbrowser(monkeypatch)
    resp = _process(_agent(), "crypto_price", {"coin_name": "bitcoin"})
    assert "Abriendo el precio" in resp["data"]["result"]
    assert opened


def test_crypto_sin_moneda():
    resp = _process(_agent(), "crypto_price")
    assert "criptomoneda" in resp["data"]["result"]


# ==================== NOTICIAS ====================

def test_news_rss(monkeypatch):
    titles = [f"Titular {i}" for i in range(5)]
    monkeypatch.setattr(web_module, "feedparser", _FakeFeedparser(titles))
    monkeypatch.setattr(web_module, "_FEEDPARSER_AVAILABLE", True)
    resp = _process(_agent(), "news_query")
    assert resp["data"]["source"] == "rss"
    assert "- Titular 0" in resp["data"]["result"]
    assert "- Titular 4" in resp["data"]["result"]
    assert len(resp["data"]["headlines"]) == 5


def test_news_con_tema(monkeypatch):
    monkeypatch.setattr(
        web_module, "feedparser", _FakeFeedparser(["Deporte titular"])
    )
    monkeypatch.setattr(web_module, "_FEEDPARSER_AVAILABLE", True)
    resp = _process(_agent(), "news_query", text="noticias de deportes")
    assert "- Deporte titular" in resp["data"]["result"]


def test_news_sin_feedparser(monkeypatch):
    monkeypatch.setattr(web_module, "_FEEDPARSER_AVAILABLE", False)
    opened = _spy_webbrowser(monkeypatch)
    resp = _process(_agent(), "news_query")
    assert "Abriendo Google News" in resp["data"]["result"]
    assert opened


def test_news_sin_titulares(monkeypatch):
    monkeypatch.setattr(web_module, "feedparser", _FakeFeedparser([]))
    monkeypatch.setattr(web_module, "_FEEDPARSER_AVAILABLE", True)
    resp = _process(_agent(), "news_query")
    assert "No encontr" in resp["data"]["result"]


# ==================== CAMBIO E INVERSIONES ====================

def test_exchange_rate_fallback(monkeypatch):
    opened = _spy_webbrowser(monkeypatch)
    resp = _process(_agent(), "get_exchange_rate", text="cuanto esta el dolar")
    assert resp["data"]["source"] == "google"
    assert "Abriendo la b" in resp["data"]["result"]
    assert opened and "google.com" in opened[0]


def test_investments_fallback(monkeypatch):
    opened = _spy_webbrowser(monkeypatch)
    resp = _process(_agent(), "check_investments", text="mis inversiones")
    assert resp["data"]["source"] == "google"
    assert "Abriendo la b" in resp["data"]["result"]
    assert opened and "google.com" in opened[0]
