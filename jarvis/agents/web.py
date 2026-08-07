"""
agents/web.py - Web Agent (SEMANA 5, FASE 2)

Búsqueda y consulta de información en línea:
- search_info: Wikipedia (1a), DuckDuckGo HTML (2a), Google como fallback
- news_query: Google News RSS via feedparser (opcional)
- weather_query: Open-Meteo (geocoding + pronóstico, sin key)
- crypto_price: CoinGecko (precio USD + variación 24h, sin key)
- get_exchange_rate / check_investments: fallback elegante abriendo el buscador

Todas las llamadas HTTP se hacen por requests.get() y feedparser.parse()
para poder mockearlas en los tests. Si falta una librería, se degrada
elegante sin lanzar excepciones.
"""

import re
import webbrowser
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from agents.base import AgentBase

# Librerías opcionales (imports seguros)
try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin requests
    requests = None
    _REQUESTS_AVAILABLE = False

try:
    import feedparser
    _FEEDPARSER_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin feedparser
    feedparser = None
    _FEEDPARSER_AVAILABLE = False

try:
    import wikipedia
    _WIKIPEDIA_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin wikipedia
    wikipedia = None
    _WIKIPEDIA_AVAILABLE = False

_USER_AGENT = {"User-Agent": "JarvisBot/1.0 (asistente personal)"}

# Criptomonedas comunes -> id oficial de CoinGecko
_COINS: Dict[str, str] = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "ether": "ethereum",
    "eth": "ethereum",
    "solana": "solana",
    "sol": "solana",
    "cardano": "cardano",
    "ada": "cardano",
    "dogecoin": "dogecoin",
    "doge": "dogecoin",
    "ripple": "ripple",
    "xrp": "ripple",
    "polkadot": "polkadot",
    "dot": "polkadot",
    "litecoin": "litecoin",
    "ltc": "litecoin",
    "binance coin": "binancecoin",
    "bnb": "binancecoin",
    "tether": "tether",
    "usdt": "tether",
    "polygon": "matic-network",
    "matic": "matic-network",
    "avalanche": "avalanche-2",
    "avax": "avalanche-2",
}

# Códigos WMO -> descripción en español
_WMO: Dict[int, str] = {
    0: "despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "con niebla",
    48: "con niebla y escarcha",
    51: "con llovizna ligera",
    53: "con llovizna",
    55: "con llovizna fuerte",
    61: "con lluvia ligera",
    63: "con lluvia moderada",
    65: "con lluvia fuerte",
    66: "con lluvia helada ligera",
    67: "con lluvia helada fuerte",
    71: "con nieve ligera",
    73: "con nieve moderada",
    75: "con nieve fuerte",
    77: "con nieve granulada",
    80: "con chubascos ligeros",
    81: "con chubascos",
    82: "con chubascos fuertes",
    85: "con chubascos de nieve ligeros",
    86: "con chubascos de nieve fuertes",
    95: "con tormenta",
    96: "con tormenta y granizo",
    99: "con tormenta fuerte y granizo",
}

_WEATHER_PHRASES = [
    "que temperatura hace en", "que temperatura hace", "temperatura en",
    "cuanto calor hace en", "tiempo en", "tiempo de", "clima en", "clima de",
    "como esta el clima en", "como esta el clima", "weather in", "weather",
    "clima", "tiempo", "temperature",
]

_NEWS_PHRASES = [
    "ultimas noticias de", "ultimas noticias", "noticias de", "noticias sobre",
    "noticias acerca de", "dame las noticias", "noticias", "news about",
    "news",
]

_SEARCH_PHRASES = [
    "busca informacion sobre", "busca informacion de", "busca en internet sobre",
    "busca en internet", "investiga sobre", "informacion sobre", "busca",
    "investiga", "que es", "quien es", "search for", "look up", "search",
]

_EXCHANGE_PHRASES = [
    "tipo de cambio", "cuanto esta el dolar", "cuanto vale el dolar",
    "precio del dolar", "cambio de moneda", "valor del dolar", "dolar",
    "exchange rate",
]

_INVESTMENT_PHRASES = [
    "como van mis inversiones", "como estan mis inversiones",
    "estado de mis inversiones", "mis inversiones", "mis acciones",
    "portfolio", "portafolio", "inversiones", "investments",
]


class WebAgent(AgentBase):
    """Agente de búsqueda y consulta de información en línea."""

    def __init__(
        self,
        agent_type: str = "web_agent",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=agent_type, agent_type=agent_type, config=config)
        self._handlers: Dict[str, Any] = {
            "search_info": self._search_info,
            "news_query": self._news,
            "weather_query": self._weather,
            "get_exchange_rate": self._exchange_rate,
            "crypto_price": self._crypto_price,
            "check_investments": self._investments,
        }

    # ==================== PUNTO DE ENTRADA ====================

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un mensaje y resuelve la consulta web.

        Args:
            message: Dict con "intent"/"name", "parameters"/"entities" y
                     "text"/"user_input" (opcional).

        Returns:
            {"status": ..., "data": {"result": ...}, "agent": "web_agent"}
        """
        if not isinstance(message, dict):
            return self._result(
                "error", {"result": "Mensaje inválido", "source": "internal"}
            )

        intent = message.get("intent") or message.get("name") or ""
        params = message.get("parameters") or message.get("entities") or {}
        if not isinstance(params, dict):
            params = {}
        user_input = (
            message.get("text")
            or message.get("user_input")
            or message.get("input")
            or ""
        )

        handler = self._handlers.get(intent)
        if handler is None:
            return self._result(
                "success",
                {"result": f"Intención '{intent}' en desarrollo", "source": "internal"},
            )

        try:
            data = handler(params, user_input)
            return self._result("success", data)
        except Exception as e:
            self.record_error(f"process:{intent}", e)
            return self._result(
                "error", {"intent": intent, "error": str(e), "source": "internal"}
            )

    def handle_event(self, event: Dict[str, Any]) -> None:
        """Reacciona a eventos del bus (por ahora solo registra)."""
        self.logger.debug(f"Evento recibido: {event}")

    def get_info(self) -> Dict[str, Any]:
        """Información del agente más sus capacidades y dependencias."""
        info = super().get_info()
        info["capabilities"] = list(self._handlers.keys())
        info["dependencies"] = {
            "wikipedia": _WIKIPEDIA_AVAILABLE,
            "requests": _REQUESTS_AVAILABLE,
            "feedparser": _FEEDPARSER_AVAILABLE,
        }
        return info

    # ==================== BÚSQUEDA (Wikipedia -> DuckDuckGo -> Google) =========

    def _search_info(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Busca información sobre un tema."""
        query = (params.get("topic") or params.get("query") or "").strip()
        if not query:
            query = self._after_phrase(user_input, _SEARCH_PHRASES)
        if not query:
            return {"result": "¿Sobre qué tema quieres que busque información?"}

        if _WIKIPEDIA_AVAILABLE:
            try:
                wikipedia.set_lang("es")
                summary = wikipedia.summary(query, sentences=2)
                return {"result": summary, "source": "wikipedia"}
            except wikipedia.exceptions.DisambiguationError:
                return {
                    "result": f"Encontré varios significados para '{query}'. "
                              "Sé más específico.",
                    "source": "wikipedia",
                }
            except wikipedia.exceptions.PageError:
                pass
            except Exception as e:  # pragma: no cover - red/API impredecible
                self.record_error("wikipedia", e)

        if _REQUESTS_AVAILABLE:
            try:
                snippets = self._duckduckgo(query)
                if snippets:
                    return {"result": snippets[0], "source": "duckduckgo"}
            except Exception as e:  # pragma: no cover - red/API impredecible
                self.record_error("duckduckgo", e)

        webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
        return {"result": f"Abriendo la búsqueda de '{query}' en Google",
                "source": "google"}

    def _duckduckgo(self, query: str, limit: int = 3) -> List[str]:
        """Consulta la versión HTML de DuckDuckGo (sin key)."""
        url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        resp = requests.get(url, timeout=15, headers=_USER_AGENT)
        resp.raise_for_status()
        html = resp.text

        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)

        results: List[str] = []
        for i in range(min(limit, len(titles))):
            title = re.sub(r"<[^>]+>", "", titles[i]).strip()
            snippet = ""
            if i < len(snippets):
                snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            results.append(f"{title}. {snippet}" if snippet else title)
        return results

    # ==================== CLIMA (Open-Meteo) ====================

    def _weather(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Clima real de una ciudad vía Open-Meteo (sin key)."""
        location = (
            params.get("location")
            or params.get("city")
            or params.get("place")
            or ""
        ).strip()
        if not location:
            location = self._after_phrase(user_input, _WEATHER_PHRASES)
        if not location:
            return {"result": "¿De qué ciudad quieres el clima?"}

        if not _REQUESTS_AVAILABLE:
            webbrowser.open("https://www.google.com/search?q=clima+hoy")
            return {"result": "Abriendo el clima de hoy en Google", "source": "google"}

        geo = self._get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": location, "count": 1, "language": "es", "format": "json"},
        )
        if not geo or not geo.get("results"):
            return {"result": f"No encontré el lugar '{location}'.", "source": "open_meteo"}

        place = geo["results"][0]
        name = place.get("name") or location
        forecast = self._get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": place.get("latitude"),
                "longitude": place.get("longitude"),
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "timezone": "auto",
            },
        )
        if not forecast:
            return {"result": f"No pude obtener el clima de '{name}'.",
                    "source": "open_meteo"}

        current = forecast.get("current") or {}
        temp = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        condition = self._wmo_description(current.get("weather_code"))

        if temp is None:
            return {"result": f"No pude obtener el clima de '{name}'.",
                    "source": "open_meteo"}

        result = f"Clima en {name}: {condition}, {temp}°C"
        if humidity is not None:
            result += f" y humedad del {humidity}%"
        result += "."
        return {"result": result, "location": name, "source": "open_meteo"}

    @staticmethod
    def _wmo_description(code: Optional[int]) -> str:
        """Traduce un código WMO a una descripción en español."""
        if code is None:
            return "condición desconocida"
        return _WMO.get(code, f"código {code}")

    # ==================== CRIPTO (CoinGecko) ====================

    def _crypto_price(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Precio en USD y variación 24h de una criptomoneda."""
        coin = (params.get("coin_name") or params.get("coin") or "").strip().lower()
        coin_id = self._normalize_coin(coin) or self._coin_from_text(user_input)
        if not coin_id:
            return {
                "result": "¿De qué criptomoneda quieres el precio? "
                          "(bitcoin, ethereum, solana...)",
                "source": "clarification",
            }

        if not _REQUESTS_AVAILABLE:
            webbrowser.open("https://www.google.com/search?q=precio+de+criptomonedas")
            return {"result": "Abriendo el precio de criptomonedas en Google",
                    "source": "google"}

        data = self._get_json(
            "https://api.coingecko.com/api/v3/simple/price",
            {"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
        )
        if not data or coin_id not in data or data[coin_id].get("usd") is None:
            return {"result": f"No encontré la criptomoneda '{coin_id}'.",
                    "source": "coingecko"}

        price = data[coin_id]["usd"]
        change = data[coin_id].get("usd_24h_change")
        result = f"{coin_id}: {price:,.2f} USD"
        if change is not None:
            direction = "subió" if change >= 0 else "bajó"
            result += f". En 24h {direction} {abs(change):.2f}%"
        result += "."
        return {"result": result, "coin": coin_id, "source": "coingecko"}

    @staticmethod
    def _normalize_coin(coin: str) -> Optional[str]:
        """Devuelve el id de CoinGecko para un nombre/alias dado."""
        if not coin:
            return None
        return _COINS.get(coin)

    @classmethod
    def _coin_from_text(cls, text: str) -> Optional[str]:
        """Detecta una criptomoneda mencionada dentro del texto."""
        low = f" {text.lower()} "
        for alias, coin_id in _COINS.items():
            if f" {alias} " in low:
                return coin_id
        return None

    # ==================== NOTICIAS (RSS) ====================

    def _news(self, params: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """Resume 3-5 titulares recientes de Google News (RSS)."""
        topic = (params.get("topic") or "").strip()
        if not topic:
            topic = self._after_phrase(user_input, _NEWS_PHRASES)

        if not _FEEDPARSER_AVAILABLE:
            webbrowser.open("https://news.google.com/")
            return {"result": "Abriendo Google News en tu navegador.",
                    "source": "google_news"}

        if topic:
            url = (
                "https://news.google.com/rss/search"
                f"?q={quote(topic)}&hl=es&gl=ES&ceid=ES:es"
            )
        else:
            url = "https://news.google.com/rss?hl=es&gl=ES&ceid=ES:es"

        feed = feedparser.parse(url)
        entries = feed.get("entries") or []
        headlines = [e.get("title") for e in entries if e.get("title")][:5]
        if not headlines:
            return {"result": "No encontré noticias en este momento.", "source": "rss"}

        lines = "\n".join(f"- {headline}" for headline in headlines)
        return {"result": lines, "headlines": headlines, "source": "rss"}

    # ==================== CAMBIO E INVERSIONES (fallback elegante) ===========

    def _exchange_rate(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Tipo de cambio: abre el buscador como fallback."""
        return self._open_search(user_input, "tipo de cambio", _EXCHANGE_PHRASES)

    def _investments(
        self, params: Dict[str, Any], user_input: str
    ) -> Dict[str, Any]:
        """Estado de inversiones: abre el buscador como fallback."""
        return self._open_search(user_input, "mis inversiones", _INVESTMENT_PHRASES)

    def _open_search(
        self, user_input: str, default_query: str, phrases: List[str]
    ) -> Dict[str, Any]:
        """Abre Google con la consulta derivada del texto del usuario."""
        query = self._after_phrase(user_input, phrases) or default_query
        webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
        return {"result": f"Abriendo la búsqueda de '{query}' en Google.",
                "source": "google"}

    # ==================== UTILIDADES ====================

    def _get_json(
        self, url: str, params: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """GET con timeout y User-Agent, devolviendo dict o None."""
        try:
            resp = requests.get(
                url, params=params or {}, timeout=15, headers=_USER_AGENT
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.record_error("http", e)
            return None

    @staticmethod
    def _after_phrase(text: str, phrases: List[str]) -> str:
        """Devuelve el texto tras la primera frase encontrada (si existe)."""
        if not text:
            return ""
        low = text.lower()
        for phrase in sorted(phrases, key=len, reverse=True):
            idx = low.find(phrase)
            if idx >= 0:
                rest = text[idx + len(phrase):]
                return rest.strip(" ¿?¡!.,:-;")
        return text.strip(" ¿?¡!.,:-;")

    @staticmethod
    def _result(status: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la respuesta estándar del agente."""
        return {"status": status, "data": data, "agent": "web_agent"}
