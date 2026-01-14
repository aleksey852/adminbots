"""
Content Loader — Загрузка и кэширование content.py для ботов.

Поддерживает:
- Загрузку контента из папки бота
- Кэширование для производительности
- Горячую перезагрузку при изменении через панель
- Fallback на дефолтный контент
"""
import importlib
import importlib.util
import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache: bot_id -> content module
_content_cache: Dict[int, Any] = {}

# Cache: bot_id -> manifest_path
_path_cache: Dict[int, str] = {}

# Default content for fallback
_default_content = None


def _get_default_content():
    """Get default content module (lazy load)"""
    global _default_content
    if _default_content is None:
        try:
            from bots._template import content
            _default_content = content
        except ImportError:
            # Create minimal fallback
            class MinimalContent:
                WELCOME = "Добро пожаловать!"
                MENU = "Меню"
                ERROR_GENERIC = "Произошла ошибка"
            _default_content = MinimalContent()
    return _default_content


def register_bot_path(bot_id: int, manifest_path: str):
    """Register bot's manifest path for content loading"""
    _path_cache[bot_id] = manifest_path
    logger.debug(f"Registered content path for bot {bot_id}: {manifest_path}")


def get_bot_content(bot_id: int) -> Any:
    """
    Get content module for a bot.
    
    Returns the content.py module from the bot's folder,
    with fallback to default template content.
    """
    # Check cache
    if bot_id in _content_cache:
        return _content_cache[bot_id]
    
    # Get manifest path
    manifest_path = _path_cache.get(bot_id)
    
    if not manifest_path:
        # Try to get from database
        try:
            import asyncio
            from database.panel_db import get_bot_by_id
            
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't await in running loop, use cached or default
                logger.warning(f"Cannot load content for bot {bot_id} in async context, using default")
                return _get_default_content()
            
            bot = loop.run_until_complete(get_bot_by_id(bot_id))
            if bot and bot.get('manifest_path'):
                manifest_path = bot['manifest_path']
                _path_cache[bot_id] = manifest_path
        except Exception as e:
            logger.error(f"Failed to get manifest path for bot {bot_id}: {e}")
    
    if not manifest_path:
        logger.warning(f"No manifest path for bot {bot_id}, using default content")
        return _get_default_content()
    
    # Load content.py from bot folder
    content_path = os.path.join(manifest_path, 'content.py')
    
    if not os.path.exists(content_path):
        logger.warning(f"content.py not found at {content_path}, using default")
        return _get_default_content()
    
    try:
        spec = importlib.util.spec_from_file_location(
            f"content_{bot_id}", content_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        _content_cache[bot_id] = module
        logger.info(f"Loaded content for bot {bot_id} from {content_path}")
        return module
        
    except Exception as e:
        logger.error(f"Failed to load content.py for bot {bot_id}: {e}")
        return _get_default_content()


def reload_content(bot_id: int) -> bool:
    """
    Reload content after changes via panel.
    
    Returns True if reload successful, False otherwise.
    """
    # Clear cache
    _content_cache.pop(bot_id, None)
    
    try:
        # Force reload
        content = get_bot_content(bot_id)
        logger.info(f"Reloaded content for bot {bot_id}")
        return content is not None
    except Exception as e:
        logger.error(f"Failed to reload content for bot {bot_id}: {e}")
        return False


def get_text(bot_id: int, key: str, default: str = None, **kwargs) -> str:
    """
    Get a text constant from bot's content.
    
    Args:
        bot_id: Bot database ID
        key: Content key (e.g., "WELCOME", "MENU")
        default: Default value if key not found
        **kwargs: Format placeholders
    
    Returns:
        Formatted text string
    """
    content = get_bot_content(bot_id)
    
    text = getattr(content, key, None)
    if text is None:
        text = default or f"[{key}]"
    
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError as e:
            logger.warning(f"Missing placeholder in {key}: {e}")
    
    return text


def get_faq(bot_id: int) -> Dict[str, str]:
    """Get FAQ items for a bot"""
    content = get_bot_content(bot_id)
    return getattr(content, 'FAQ_ITEMS', {})


def get_buttons(bot_id: int) -> Dict[str, str]:
    """Get all button texts for a bot"""
    content = get_bot_content(bot_id)
    
    buttons = {}
    for key in dir(content):
        if key.startswith('BTN_'):
            buttons[key] = getattr(content, key)
    
    return buttons


def list_content_keys(bot_id: int) -> Dict[str, str]:
    """
    List all content keys and their values for a bot.
    Used by content editor in panel.
    """
    content = get_bot_content(bot_id)
    
    result = {}
    for key in dir(content):
        if key.startswith('_'):
            continue
        value = getattr(content, key)
        if isinstance(value, str):
            result[key] = value
        elif isinstance(value, dict):
            result[key] = value
    
    return result


def clear_cache():
    """Clear all content caches"""
    global _content_cache, _default_content
    _content_cache.clear()
    _default_content = None
    logger.info("Content cache cleared")
