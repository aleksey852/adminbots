# Кастомные Боты

Эта директория предназначена для размещения кастомных ботов, которые требуют логику, выходящую за рамки стандартных модулей (receipts, promo).

## Требования к Боту

Чтобы кастомный бот мог управляться через Admin Panel, он должен соответствовать следующим требованиям:

### 1. Структура директории

```
bots/
└── my_custom_bot/
    ├── __init__.py          # Экспортирует custom_bot инстанс
    ├── manifest.json        # Метаданные бота
    └── handlers.py          # Логика бота
```

### 2. manifest.json

```json
{
  "name": "my_custom_bot",
  "version": "1.0.0",
  "description": "Описание функционала",
  "author": "Ваше имя",
  
  "required_modules": ["registration"],
  
  "panel_capabilities": {
    "users": true,
    "campaigns": true,
    "texts": true,
    "receipts": false,
    "codes": true,
    "custom_settings": [
      {"key": "special_mode", "type": "checkbox", "label": "Особый режим"}
    ]
  }
}
```

### 3. Наследование от BotModule

```python
# handlers.py
from modules.base import BotModule
from aiogram import Router, F
from aiogram.types import Message

class CustomBotModule(BotModule):
    name = "my_custom_bot"
    version = "1.0.0"
    description = "Мой кастомный бот"
    default_enabled = True
    
    # Настройки для Admin Panel
    settings_schema = {
        "special_mode": {
            "type": "checkbox",
            "label": "Особый режим",
            "default": False
        }
    }
    
    def _setup_handlers(self):
        @self.router.message(F.text == "/custom")
        async def custom_command(message: Message):
            await message.answer("Кастомная команда!")

# __init__.py
from .handlers import CustomBotModule
custom_bot = CustomBotModule()
```

### 4. Автодискавери

Модуль автоматически обнаружится при запуске бота, если:
- Папка содержит `__init__.py`
- Экспортируется инстанс класса, наследуемого от `BotModule`

## Возможности Panel

Panel сможет:
- ✅ Включать/выключать кастомный модуль
- ✅ Редактировать настройки через `settings_schema`
- ✅ Показывать пользователей и их статистику
- ✅ Отправлять рассылки
- ✅ Управлять текстами (если используется `config_manager`)

## Пример использования config_manager

```python
from utils.config_manager import config_manager

async def get_welcome_text(bot_id: int) -> str:
    return config_manager.get_setting("welcome_text", "Добро пожаловать!", bot_id)
```
