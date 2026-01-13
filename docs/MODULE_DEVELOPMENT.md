# Module Development Guide

> Как создать новый модуль для Admin Bots Framework

## Quick Start

```bash
# 1. Copy template
cp -r modules/_template modules/my_module

# 2. Edit metadata in handlers.py
# 3. Implement handlers
# 4. Create README.md
# 5. Module auto-loads on restart
```

---

## Module Structure

```
modules/my_module/
├── __init__.py          # REQUIRED: exports module instance
├── README.md            # REQUIRED: documentation
├── handlers.py          # REQUIRED: aiogram handlers
├── schemas.py           # Optional: Pydantic models
├── db/
│   ├── methods.py       # Optional: database operations
│   └── migrations.sql   # Optional: table definitions
└── api/
    └── routes.py        # Optional: admin panel API
```

---

## Base Class

```python
from core.module_base import BotModule
from aiogram import Router

class MyModule(BotModule):
    # === REQUIRED ===
    name = "my_module"           # Unique identifier
    version = "1.0.0"
    description = "Module description"
    
    # === OPTIONAL ===
    dependencies = ["core"]      # Other modules this depends on
    default_enabled = True       # Enabled by default for new bots
    
    # Settings schema for admin UI
    settings_schema = {
        "max_items": {
            "type": "number",
            "label": "Maximum items",
            "default": 10
        }
    }
    
    def _setup_handlers(self):
        """Register aiogram handlers"""
        
        @self.router.message(F.text == "🎯 My Button")
        async def my_handler(message: Message, bot_id: int):
            # bot_id injected by middleware
            setting = self.get_config(bot_id, "max_items", 10)
            await message.answer(f"Max items: {setting}")

# Export instance
my_module = MyModule()
```

---

## Settings Schema Types

| Type | UI Element | Example |
|------|------------|---------|
| `text` | Text input | `{"type": "text", "label": "Name"}` |
| `number` | Number input | `{"type": "number", "default": 10}` |
| `checkbox` | Toggle | `{"type": "checkbox", "default": false}` |
| `textarea` | Multi-line | `{"type": "textarea"}` |
| `select` | Dropdown | `{"type": "select", "options": ["a", "b"]}` |

---

## Database Access

```python
# modules/my_module/db/methods.py
from database.bot_db import bot_db_manager

async def get_items(bot_id: int, user_id: int):
    db = bot_db_manager.get(bot_id)
    async with db.get_connection() as conn:
        return await conn.fetch(
            "SELECT * FROM my_items WHERE user_id = $1",
            user_id
        )
```

---

## Event Bus (Inter-module Communication)

```python
from core.event_bus import event_bus

# Emit event
await event_bus.emit("my_module.item_created", {
    "user_id": 123,
    "item_id": 456
}, bot_id=1)

# Listen to events
@event_bus.on("promo.code_activated")
async def on_promo_activated(data, bot_id):
    user_id = data["user_id"]
    # React to promo activation
```

---

## README Template

Every module MUST have a README.md. Use this template:

```markdown
# Module Name

Brief description.

## Dependencies
- `core`

## Settings
| Key | Type | Default | Description |
|-----|------|---------|-------------|

## Handlers
| Trigger | Handler | Description |
|---------|---------|-------------|

## Database Tables
- `table_name` — description

## Events
### Emits
- `module.event_name` — { field1, field2 }

### Listens
- `other.event` — reaction
```

---

## Checklist

- [ ] Unique `name` in class
- [ ] `README.md` with full documentation
- [ ] All handlers receive `bot_id` parameter
- [ ] Settings use `settings_schema` for UI
- [ ] No direct imports from other modules
- [ ] Events documented if used

---

## Monitoring Integration

Modules can expose status and health for dashboards:

```python
class MyModule(BotModule):
    async def get_status(self, bot_id: int):
        """Called by Status Dashboard to get current state."""
        return {
            **await super().get_status(bot_id),
            "pending_items": await self.get_pending_count(bot_id),
            "last_activity": self.last_activity_at
        }
    
    async def get_health(self, bot_id: int):
        """Called for health checks. Report any issues."""
        issues = []
        if not await self.check_api_connection():
            issues.append("External API unreachable")
        return {"healthy": len(issues) == 0, "issues": issues}
```

A Status module can then query all modules:

```python
from core import module_loader

async def get_all_statuses(bot_id):
    return {
        m.name: await m.get_status(bot_id) 
        for m in module_loader.get_all_modules()
    }
```

---

## State Protection (Anti-Hang)

Protect users from getting "stuck" in your module:

### 1. Always provide cancel option
```python
cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
])
await message.answer("📱 Введите телефон:", reply_markup=cancel_kb)
```

### 2. Declare your states
```python
class ProfileModule(BotModule):
    states = ["editing_name", "editing_phone"]
    state_timeout = 600  # 10 min auto-clear
```

### 3. Handle unexpected input gracefully
```python
@self.router.message()
async def fallback(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
        await message.answer("🤔 Не понял. Вот меню:", reply_markup=main_kb)
```

Core module handles `/cancel` globally for all modules.
