"""
servidor_ws.py - Servidor WebSocket para conectar la esfera visual con el orquestador

Puente entre el EventBus de Jarvis (Python) y el frontend Three.js (navegador).
Recibe eventos del orquestador y los reenvía por WebSocket a jarvis_esfera.html.

Puerto: 8765
Eventos que reenvía:
- STATE_CHANGED: {event:"STATE_CHANGED", payload:{to:"idle/escuchando/procesando/hablando"}}
- SPEAKING_STARTED: {event:"SPEAKING_STARTED", payload:{}}
- SPEAKING_ENDED: {event:"SPEAKING_ENDED", payload:{}}
"""

import asyncio
import json
import logging
import sys
import os
from typing import Set

# Añadir path para importar módulos de jarvis
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets
from jarvis.orchestrator.events import get_event_bus, JarvisEvent, Event


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("Jarvis.WSServer")


class WebSocketServer:
    """Servidor WebSocket que puentea EventBus → Navegador."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.event_bus = get_event_bus()
        self._running = False
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        """Suscribe al EventBus los eventos que deben ir al frontend."""
        events_to_forward = [
            JarvisEvent.STATE_CHANGED,
            JarvisEvent.SPEAKING_STARTED,
            JarvisEvent.SPEAKING_ENDED,
        ]
        for evt in events_to_forward:
            self.event_bus.subscribe(evt.value, self._on_event)
        logger.info("Suscrito a eventos: %s", [e.value for e in events_to_forward])

    def _on_event(self, event: Event) -> None:
        """Callback del EventBus: convierte evento a JSON y lo broadcast."""
        message = json.dumps({
            "event": event.name,
            "payload": event.payload
        })
        # Ejecutar broadcast en el loop asyncio de forma thread-safe
        asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    async def _broadcast(self, message: str) -> None:
        """Envía mensaje a todos los clientes conectados."""
        if not self.clients:
            return
        disconnected = set()
        for client in self.clients:
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
            except Exception as e:
                logger.warning("Error enviando a cliente: %s", e)
                disconnected.add(client)
        self.clients -= disconnected

    async def _handler(self, websocket: websockets.WebSocketServerProtocol) -> None:
        """Maneja conexión individual de un cliente."""
        self.clients.add(websocket)
        client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
        logger.info("Cliente conectado: %s (total: %d)", client_ip, len(self.clients))

        try:
            # Enviar estado inicial al conectar
            await websocket.send(json.dumps({
                "event": "STATE_CHANGED",
                "payload": {"to": "idle"}
            }))
            # Mantener conexión viva (ping/pong automático de websockets)
            async for _ in websocket:
                pass  # Ignorar mensajes entrantes del cliente por ahora
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error("Error en handler WS: %s", e)
        finally:
            self.clients.discard(websocket)
            logger.info("Cliente desconectado: %s (total: %d)", client_ip, len(self.clients))

    async def start(self) -> None:
        """Inicia el servidor WebSocket."""
        self._loop = asyncio.get_running_loop()
        self._running = True
        logger.info("Iniciando WebSocket server en ws://%s:%d", self.host, self.port)
        async with websockets.serve(self._handler, self.host, self.port):
            await asyncio.Future()  # Corre para siempre

    def stop(self) -> None:
        """Detiene el servidor."""
        self._running = False
        for client in self.clients.copy():
            asyncio.run_coroutine_threadsafe(client.close(), self._loop)
        logger.info("WebSocket server detenido")


# Variable global para acceso desde el orquestador
_ws_server: WebSocketServer = None


def get_ws_server() -> WebSocketServer:
    """Obtiene la instancia global del servidor WS."""
    global _ws_server
    if _ws_server is None:
        _ws_server = WebSocketServer()
    return _ws_server


async def run_ws_server() -> None:
    """Función de conveniencia para arrancar el servidor."""
    server = get_ws_server()
    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(run_ws_server())
    except KeyboardInterrupt:
        logger.info("Servidor detenido por usuario")