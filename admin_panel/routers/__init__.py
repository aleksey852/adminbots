"""Admin Panel Routers Package"""
from .auth import router as auth_router
from .bots import router as bots_router
from .users import router as users_router
from .campaigns import router as campaigns_router
from .system import router as system_router
from .texts import router as texts_router

__all__ = [
    'auth_router',
    'system_router',
    'users_router',
    'bots_router',
    'campaigns_router',
    'texts_router'
]
