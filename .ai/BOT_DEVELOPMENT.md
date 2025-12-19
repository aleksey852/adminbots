# Admin Bots Platform — AI Development Guide

> **Для ИИ-ассистентов**: Используй этот документ для создания ботов на платформе.

## 🎯 Ключевые принципы

1. **Бот = Конфигурация** — никакого Python кода в самом боте
2. **Модули из библиотеки** — используй существующие модули из `modules/`
3. **Тексты в content.py** — все строки в одном файле

---

## 📁 Структура бота

Создавай бота в папке `bots/<bot_name>/` с 3 файлами:

```
bots/my_bot/
├── __init__.py      # Одна строка!
├── manifest.json    # Конфигурация
└── content.py       # Все тексты
```

---

## 📄 __init__.py (копируй как есть)

```python
from bots._base import BotBase
bot = BotBase(__file__)

manifest = bot.manifest
BOT_NAME = bot.name
BOT_VERSION = bot.version
BOT_MODULES = bot.modules
get_content = lambda: bot.content
get_manifest = lambda: bot.manifest
__all__ = ['bot', 'manifest', 'BOT_NAME', 'BOT_VERSION', 'BOT_MODULES', 'get_content', 'get_manifest']
```

---

## 📄 manifest.json

```json
{
  "name": "bot_name",
  "display_name": "Отображаемое название",
  "version": "1.0.0",
  "description": "Краткое описание бота",
  
  "modules": [
    "core",
    "registration",
    // Выбери нужные:
    // "promo"     — для промокодов
    // "receipts"  — для загрузки чеков
    // "raffle"    — для розыгрышей
    // "admin"     — админ-команды
  ],
  
  "module_config": {
    "registration": {
      "subscription_required": false,
      "subscription_channel_id": null,
      "subscription_channel_url": null
    },
    // Конфиг для выбранных модулей
  },
  
  "panel_features": {
    "users": true,
    "broadcasts": true,
    "content_editor": true,
    "promo_codes": false,
    "receipts": false,
    "raffle": false
  }
}
```

---

## 📄 content.py

```python
"""Все тексты бота."""

# ОБЯЗАТЕЛЬНЫЕ (используются модулем core)
WELCOME = """
🎉 Приветственное сообщение
"""

MENU = """
📋 Главное меню
"""

PROFILE = """
👤 Ваш профиль
ID: {user_id}
Билетов: {tickets}
"""

# КНОПКИ (обязательные)
BTN_MENU = "📋 Меню"
BTN_PROFILE = "👤 Профиль"
BTN_FAQ = "❓ FAQ"
BTN_BACK = "◀️ Назад"

# FAQ
FAQ_TITLE = "❓ Часто задаваемые вопросы"
FAQ_ITEMS = {
    "Вопрос 1?": "Ответ 1",
    "Вопрос 2?": "Ответ 2",
}

# СИСТЕМНЫЕ
ERROR_GENERIC = "❌ Произошла ошибка"

# ДЛЯ МОДУЛЯ promo (если используется)
# BTN_PROMO = "🎁 Ввести промокод"
# PROMO_PROMPT = "Введите промокод:"
# PROMO_SUCCESS = "✅ Промокод активирован!"
# PROMO_INVALID = "❌ Неверный промокод"
# PROMO_ALREADY_USED = "⚠️ Этот код уже использован"

# ДЛЯ МОДУЛЯ receipts (если используется)
# BTN_UPLOAD_RECEIPT = "📷 Загрузить чек"
# RECEIPT_PROMPT = "Отправьте фото чека"
# RECEIPT_RECEIVED = "✅ Чек получен!"
# RECEIPT_APPROVED = "🎉 Чек одобрен!"
# RECEIPT_REJECTED = "❌ Чек отклонён: {reason}"

# ДЛЯ МОДУЛЯ raffle (если используется)
# RAFFLE_INFO = "🎰 Розыгрыш. Ваши билеты: {tickets}"
# RAFFLE_WINNER = "🎊 Вы выиграли: {prize}"

# ПОДПИСКА НА КАНАЛ (если subscription_required: true)
# SUBSCRIPTION_REQUIRED = "Подпишитесь на канал: {channel_url}"
# BTN_CHECK_SUBSCRIPTION = "✅ Проверить подписку"
# SUBSCRIPTION_SUCCESS = "✅ Подписка подтверждена!"
# SUBSCRIPTION_FAILED = "❌ Вы не подписаны"
```

---

## 🔧 Доступные модули

| Модуль | Описание | Ключевые опции в module_config |
|--------|----------|-------------------------------|
| `core` | Меню, профиль, FAQ | — |
| `registration` | Регистрация | `subscription_required`, `subscription_channel_id` |
| `promo` | Промокоды | `max_codes_per_user`, `notify_admin_on_activation` |
| `receipts` | Загрузка чеков | `auto_approve`, `require_photo` |
| `raffle` | Розыгрыши | `intermediate_enabled`, `tickets_per_code` |
| `admin` | Админ в боте | — |

---

## ✅ Чек-лист перед коммитом

- [ ] Папка `bots/<name>/` создана
- [ ] `__init__.py` содержит импорт BotBase
- [ ] `manifest.json` валидный JSON с обязательными полями
- [ ] `content.py` содержит WELCOME, MENU, PROFILE, BTN_*, FAQ_*
- [ ] Модули в manifest.json соответствуют содержимому content.py

---

## 🚫 Чего НЕ делать

1. **НЕ пиши Python логику** — только конфигурация
2. **НЕ создавай handlers.py** — используй модули из библиотеки
3. **НЕ хардкодь тексты** — всё в content.py
4. **НЕ импортируй aiogram** — BotBase делает всё сам

---

## 📋 Примеры

### Промо-бот с промокодами

```json
{
  "name": "promo_bot",
  "display_name": "Промо-акция",
  "modules": ["core", "registration", "promo", "raffle", "admin"],
  "module_config": {
    "promo": { "max_codes_per_user": 5 }
  },
  "panel_features": {
    "users": true, "promo_codes": true, "raffle": true
  }
}
```

### Чековый бот

```json
{
  "name": "receipt_bot",
  "display_name": "Чековая акция",
  "modules": ["core", "registration", "receipts", "raffle", "admin"],
  "module_config": {
    "receipts": { "auto_approve": false }
  },
  "panel_features": {
    "users": true, "receipts": true, "raffle": true
  }
}
```

### Простой бот без акций

```json
{
  "name": "simple_bot",
  "display_name": "Инфо-бот",
  "modules": ["core", "registration"],
  "panel_features": {
    "users": true, "broadcasts": true
  }
}
```
