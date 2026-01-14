from fastapi import WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    Manages WebSocket connections partitioned by bot_id.
    Allows broadcasting messages to all clients viewing a specific bot.
    """
    def __init__(self):
        # Map bot_id -> List[WebSocket]
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, bot_id: int):
        await websocket.accept()
        if bot_id not in self.active_connections:
            self.active_connections[bot_id] = []
        self.active_connections[bot_id].append(websocket)
        logger.info(f"WS Client connected for bot {bot_id}. Total: {len(self.active_connections[bot_id])}")

    def disconnect(self, websocket: WebSocket, bot_id: int):
        if bot_id in self.active_connections:
            if websocket in self.active_connections[bot_id]:
                self.active_connections[bot_id].remove(websocket)
            if not self.active_connections[bot_id]:
                del self.active_connections[bot_id]
        logger.info(f"WS Client disconnected from bot {bot_id}")

    async def broadcast(self, message: Dict[str, Any], bot_id: int):
        """Broadcast JSON message to all clients connected to bot_id"""
        if bot_id in self.active_connections:
            # Copy list to avoid modification errors during iteration
            # (though strictly running in one thread loop, async context is safe-ish, but defensively copy)
            connections = self.active_connections[bot_id][:]
            for connection in connections:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to send WS message: {e}")
                    # Clean up dead connection? 
                    # Usually better to let disconnect() handle it via exception in the route handler.

# Global instance
manager = ConnectionManager()
