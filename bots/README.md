# Боты — Модульная Архитектура v3.0

**Бот = Конфигурация + Контент, НЕ код!**

## 🎯 Быстрый старт

### 1. Создайте шаблон
```bash
cp -r bots/_template bots/my_bot
```

### 2. Настройте manifest.json
```json
{
  "display_name": "Мой Бот",
  "modules": ["core", "profile", "promo", "raffle"],
  "module_config": {
    "profile": { "required_fields": ["phone"] },
    "promo": { "tickets_per_code": 3 }
  }
}
```

### 3. Отредактируйте content.py
```python
WELCOME = "🎉 Добро пожаловать в нашу акцию!"
PROMO_ACTIVATED = "✅ Код активирован! +{tickets} билетов"
```

### 4. Активируйте через панель
1. Панель → "Добавить бота"
2. Выберите шаблон из списка
3. Введите токен от @BotFather
4. Готово!

---

## 📁 Структура

```
bots/
├── _template/           # Шаблон для копирования
│   ├── __init__.py
│   ├── manifest.json    # Модули + настройки
│   └── content.py       # ВСЕ тексты бота
├── promo_example/
└── receipt_example/
```

---

## � module_config

Кастомизация модулей без написания кода:

```json
{
  "modules": ["core", "promo", "raffle"],
  "module_config": {
    "promo": {
      "max_codes_per_user": 5,
      "notify_admin_on_activation": true
    },
    "registration": {
      "subscription_required": true,
      "subscription_channel_id": -1001234567890
    }
  }
}
```

Модуль читает:
```python
max_codes = self.get_config(bot_id, 'max_codes_per_user', 1)
```

---

## 📚 Модули

| Модуль | Опции |
|--------|-------|
| `core` | - |
| `registration` | `subscription_required`, `subscription_channel_id` |
| `promo` | `max_codes_per_user`, `notify_admin_on_activation` |
| `receipts` | `auto_approve`, `require_photo` |
| `raffle` | `intermediate_enabled`, `tickets_per_code` |

---

## ➕ Новый модуль

Если нужна уникальная логика:

```python
# modules/promo_lottery/__init__.py
from modules.promo.handlers import PromoModule

class PromoLotteryModule(PromoModule):
    name = "promo_lottery"
    
    default_settings = {
        **PromoModule.default_settings,
        'lottery_chance': 0.1
    }
```

Использование:
```json
{"modules": ["core", "promo_lottery"]}
```
