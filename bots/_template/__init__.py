"""
Bot Template — Base template for creating new bots.

Этот шаблон предоставляет базовую структуру для создания ботов.
Скопируйте папку _template и переименуйте для создания нового бота.
"""
from typing import Optional
import os
import json

# Load manifest
_manifest_path = os.path.join(os.path.dirname(__file__), 'manifest.json')
with open(_manifest_path, 'r', encoding='utf-8') as f:
    manifest = json.load(f)

# Expose manifest data
BOT_NAME = manifest.get('name', '_template')
BOT_VERSION = manifest.get('version', '1.0.0')
BOT_MODULES = manifest.get('modules', [])


def get_content():
    """Get content module for this bot"""
    from . import content
    return content


def get_manifest() -> dict:
    """Get full manifest data"""
    return manifest


__all__ = ['manifest', 'BOT_NAME', 'BOT_VERSION', 'BOT_MODULES', 'get_content', 'get_manifest']
