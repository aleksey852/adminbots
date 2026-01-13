"""
Event Bus

Inter-module communication without direct imports.
Modules emit events, other modules subscribe to them.
"""
import asyncio
import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class EventBus:
    """
    Simple event bus for inter-module communication.
    
    Usage:
        # Module A: emit event
        await event_bus.emit("promo.code_activated", {"user_id": 123}, bot_id=1)
        
        # Module B: subscribe
        @event_bus.on("promo.code_activated")
        async def handle_activation(data, bot_id):
            pass
    """
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
    
    def on(self, event_name: str):
        """Decorator to subscribe to an event."""
        def decorator(handler: Callable):
            if event_name not in self._handlers:
                self._handlers[event_name] = []
            self._handlers[event_name].append(handler)
            logger.debug(f"Subscribed {handler.__name__} to {event_name}")
            return handler
        return decorator
    
    def subscribe(self, event_name: str, handler: Callable):
        """Subscribe a handler to an event (non-decorator version)."""
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)
    
    def unsubscribe(self, event_name: str, handler: Callable):
        """Unsubscribe a handler from an event."""
        if event_name in self._handlers:
            self._handlers[event_name] = [
                h for h in self._handlers[event_name] if h != handler
            ]
    
    async def emit(self, event_name: str, data: Dict[str, Any], bot_id: int):
        """
        Emit an event to all subscribers.
        
        Args:
            event_name: Event identifier (e.g., "promo.code_activated")
            data: Event payload
            bot_id: Bot context
        """
        handlers = self._handlers.get(event_name, [])
        
        if not handlers:
            logger.debug(f"No handlers for event: {event_name}")
            return
        
        logger.debug(f"Emitting {event_name} to {len(handlers)} handlers")
        
        # Run all handlers concurrently
        tasks = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    tasks.append(handler(data, bot_id))
                else:
                    # Sync handler, run in executor
                    loop = asyncio.get_event_loop()
                    tasks.append(loop.run_in_executor(None, handler, data, bot_id))
            except Exception as e:
                logger.error(f"Error preparing handler {handler.__name__} for {event_name}: {e}")
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Handler error for {event_name}: {result}")
    
    def clear(self):
        """Clear all subscriptions (useful for testing)."""
        self._handlers.clear()
    
    def get_subscriptions(self) -> Dict[str, int]:
        """Get count of handlers per event (for debugging)."""
        return {name: len(handlers) for name, handlers in self._handlers.items()}


# Global singleton
event_bus = EventBus()
