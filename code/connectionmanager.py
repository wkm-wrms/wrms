"""_summary_ Manage Server to clients communications and messages distribution.
This module defines the ConnectionManager class, which is responsible for managing WebSocket and Server-Sent Events (SSE) connections. 
It maintains lists of active connections and provides methods to broadcast messages to all connected clients through both WebSocket and SSE protocols.

"""
import asyncio
import json

from typing import List, Set
from fastapi import WebSocket


class ConnectionManager:
    """
    ConnectionManager
    A class for managing WebSocket and Server-Sent Events (SSE) connections.
    This manager maintains lists of active connections and broadcasts messages
    to all connected clients through both WebSocket and SSE protocols.
    Attributes:
        active_connections (List[WebSocket]): A list of active WebSocket connections.
        active_sse_connections (Set[asyncio.Queue]): A set of asyncio queues representing SSE connections.
    Methods:

        disconnect(websocket: WebSocket): Removes a WebSocket connection from the active list.
        connect_sse(queue: asyncio.Queue): Registers a new SSE connection queue.
        disconnect_sse(queue: asyncio.Queue): Unregisters an SSE connection queue.
        broadcast(message: dict): Sends a message to all active WebSocket and SSE connections.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.active_sse_connections: Set[asyncio.Queue] = set()

    async def connect(self, websocket: WebSocket):
        """ connect(websocket: WebSocket): Accepts and registers a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """ disconnect(websocket: WebSocket): Removes a WebSocket connection from the active list."""
        self.active_connections.remove(websocket)

    async def connect_sse(self, queue: asyncio.Queue):
        """ connect_sse(queue: asyncio.Queue): Registers a new SSE connection queue."""
        self.active_sse_connections.add(queue)

    async def disconnect_sse(self, queue: asyncio.Queue):
        """ disconnect_sse(queue: asyncio.Queue): Unregisters an SSE connection queue."""
        self.active_sse_connections.remove(queue)

    async def broadcast(self, message: dict):
        """ broadcast(message: dict): Sends a message to all active WebSocket and SSE connections."""
        # handle WebSocket connections
        for connection in self.active_connections:
            await connection.send_json(message)
        # Handle SSE connections - każda kolejka reprezentuje jedno połączenie
        for queue in self.active_sse_connections:
            try:
                await queue.put(json.dumps(message))
            except asyncio.QueueFull:
                print("Kolejka SSE jest pełna, nie można wysłać wiadomości.")
            except asyncio.CancelledError:
                print("Połączenie SSE zostało anulowane, nie można wysłać wiadomości.")
            except json.JSONDecodeError as e:
                print(
                    f"Błąd kodowania JSON, nie można wysłać wiadomości : {e}")
            except ValueError as e:
                print(f"Błąd wartości, nie można wysłać wiadomości : {e}")
