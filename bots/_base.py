"""
Bot Base — Базовый класс для ботов.

Упрощает создание ботов до минимальной конфигурации.
Бот = manifest.json + content.py. Никакого кода!

Пример использования:
    # bots/my_bot/__init__.py
    from bots._base import BotBase
    bot = BotBase(__file__)
"""
import os
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class BotBase:
    """
    Базовый класс для ботов платформы.
    
    Автоматически загружает manifest.json и content.py из папки бота.
    Бот определяется полностью через конфигурацию — никакого кода!
    
    Attributes:
        name: Имя бота из manifest
        version: Версия из manifest
        modules: Список модулей для подключения
        module_config: Конфигурация модулей
        panel_features: Доступные функции панели
    
    Example:
        # В bots/my_bot/__init__.py просто:
        from bots._base import BotBase
        bot = BotBase(__file__)
    """
    
    def __init__(self, init_file_path: str):
        """
        Initialize bot from its folder.
        
        Args:
            init_file_path: Path to __init__.py file (__file__)
        """
        self.bot_path = os.path.dirname(os.path.abspath(init_file_path))
        self.manifest = self._load_manifest()
        self._content = None
        
        # Extract common fields
        self.name = self.manifest.get('name', os.path.basename(self.bot_path))
        self.display_name = self.manifest.get('display_name', self.name)
        self.version = self.manifest.get('version', '1.0.0')
        self.description = self.manifest.get('description', '')
        
        # Module configuration
        self.modules = self.manifest.get('modules', ['core', 'registration'])
        self.module_config = self.manifest.get('module_config', {})
        
        # Panel features
        self.panel_features = self.manifest.get('panel_features', {
            'users': True,
            'broadcasts': True,
            'content_editor': True
        })
        
        logger.debug(f"Initialized bot: {self.name} v{self.version}")
    
    def _load_manifest(self) -> Dict:
        """Load manifest.json from bot folder"""
        manifest_path = os.path.join(self.bot_path, 'manifest.json')
        
        if not os.path.exists(manifest_path):
            logger.warning(f"manifest.json not found in {self.bot_path}")
            return {}
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load manifest.json: {e}")
            return {}
    
    @property
    def content(self):
        """Lazy load content module"""
        if self._content is None:
            content_path = os.path.join(self.bot_path, 'content.py')
            if os.path.exists(content_path):
                import importlib.util
                spec = importlib.util.spec_from_file_location("content", content_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self._content = module
            else:
                # Fallback to empty content
                self._content = type('EmptyContent', (), {})()
        return self._content
    
    def get_text(self, key: str, default: str = None, **kwargs) -> str:
        """
        Get text from content.py with optional formatting.
        
        Args:
            key: Content key (e.g., 'WELCOME', 'MENU')
            default: Default value if key not found
            **kwargs: Format placeholders
        
        Returns:
            Formatted text string
        
        Example:
            text = bot.get_text('WELCOME', name=user.first_name)
        """
        text = getattr(self.content, key, None)
        if text is None:
            text = default or f"[{key}]"
        
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError as e:
                logger.warning(f"Missing placeholder in {key}: {e}")
        
        return text
    
    def get_module_config(self, module_name: str, key: str = None, default: Any = None) -> Any:
        """
        Get configuration for a specific module.
        
        Args:
            module_name: Name of the module
            key: Specific config key (optional, returns all if None)
            default: Default value if not found
        
        Returns:
            Configuration value or dict
        
        Example:
            max_codes = bot.get_module_config('promo', 'max_codes_per_user', 1)
        """
        module_conf = self.module_config.get(module_name, {})
        
        if key is None:
            return module_conf
        
        return module_conf.get(key, default)
    
    def has_module(self, module_name: str) -> bool:
        """Check if bot has a module enabled"""
        return module_name in self.modules
    
    def has_feature(self, feature_name: str) -> bool:
        """Check if panel feature is enabled"""
        return self.panel_features.get(feature_name, False)
    
    def reload_content(self):
        """Reload content.py (after panel edit)"""
        self._content = None
        logger.info(f"Content reloaded for bot {self.name}")
    
    def to_dict(self) -> Dict:
        """Export bot info as dictionary"""
        return {
            'name': self.name,
            'display_name': self.display_name,
            'version': self.version,
            'description': self.description,
            'modules': self.modules,
            'panel_features': self.panel_features,
            'bot_path': self.bot_path
        }
    
    def __repr__(self):
        return f"<BotBase: {self.name} v{self.version} [{len(self.modules)} modules]>"


# Alias for backwards compatibility
Bot = BotBase
