# Мастер Чек-лист: Создание бота

> Полная документация всех модулей и переменных `content.py`

---

## 1. Файловая структура бота

```
bots/my_bot/
├── __init__.py       # пустой или from bots.my_bot import content
├── manifest.json     # Конфигурация бота
└── content.py        # ВСЕ тексты бота (единственный источник истины)
```

---

## 2. manifest.json

```json
{
    "name": "my_bot",
    "display_name": "Название для пользователей",
    "version": "1.0.0",
    "description": "Описание бота",
    "modules": ["core", "registration", "promo", "raffle", "admin"],
    "module_config": {
        "registration": {
            "subscription_required": false,
            "subscription_channel_id": null,
            "subscription_channel_url": null
        },
        "profile": {
            "fields": "name,phone,email",
            "required_fields": "phone"
        },
        "receipts": {
            "target_keywords": "чипсы,buster",
            "excluded_keywords": ""
        }
    }
}
```

---

## 3. content.py — ВСЕ переменные по модулям

### Модуль CORE (базовый, обязателен)

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `WELCOME_BACK` | `{name}`, `{count}`, `{days_text}` | Приветствие вернувшегося пользователя |
| `WELCOME_NEW` | — | Приветствие нового (начало регистрации) |
| `CANCEL_MSG` | `{count}` | Сообщение при отмене действия |
| `NOT_REGISTERED` | — | Пользователь не зарегистрирован |
| `ERROR_INIT` | — | Ошибка инициализации бота |
| `ERROR_AUTH` | — | Ошибка авторизации |
| `STATUS` | `{name}`, `{tickets}`, `{days}` | Статус пользователя |
| `NO_RECEIPTS_PROMO` | — | Нет активаций (промо-бот) |
| `NO_RECEIPTS_RECEIPT` | — | Нет чеков (чек-бот) |
| `RECEIPTS_LIST_PROMO` | `{total}` | Заголовок списка активаций |
| `RECEIPTS_LIST_RECEIPT` | `{total}` | Заголовок списка чеков |
| `FAQ_TITLE` | — | Заголовок FAQ |
| `SUPPORT_MSG` | — | Сообщение поддержки |
| `PROFILE_PROMO` | `{name}`, `{phone}`, `{total}`, `{tickets}`, `{wins_text}`, `{days_text}` | Профиль (промо) |
| `PROFILE_RECEIPT` | `{name}`, `{phone}`, `{total}`, `{tickets}`, `{wins_text}`, `{days_text}` | Профиль (чеки) |
| `HELP_PROMO` | — | Помощь (промо-бот) |
| `HELP_RECEIPT` | — | Помощь (чек-бот) |
| `TICKETS_INFO` | `{content}` | Обёртка информации о билетах |
| `TICKETS_EMPTY_PROMO` | — | Нет билетов (промо) |
| `TICKETS_EMPTY_RECEIPT` | — | Нет билетов (чеки) |
| `TICKETS_MECHANICS_PROMO` | — | Механика билетов (промо) |
| `TICKETS_MECHANICS_RECEIPT` | — | Механика билетов (чеки) |
| `SUB_CHECK_SUCCESS` | — | Подписка подтверждена |
| `SUB_CHECK_FAIL` | — | Подписка не найдена |
| `SUB_WARNING` | — | Требуется подписка |

### FAQ ключи (модуль CORE)

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `FAQ_HOW_PROMO` | — | Как участвовать (промо-бот) |
| `FAQ_HOW_RECEIPT` | — | Как участвовать (чек-бот) |
| `FAQ_LIMIT_PROMO` | — | Лимиты промокодов |
| `FAQ_LIMIT_RECEIPT` | — | Лимиты чеков |
| `FAQ_WIN` | — | Как узнать о выигрыше |
| `FAQ_REJECT_PROMO` | — | Промокод не принят |
| `FAQ_REJECT_RECEIPT` | — | Чек не принят |
| `FAQ_DATES` | `{start}`, `{end}` | Даты акции |
| `FAQ_PRIZES` | — | Информация о призах |
| `FAQ_RAFFLE` | — | Механика розыгрышей |

---

### Модуль PROMO

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `PROMO_PROMPT` | — | Введите промокод |
| `PROMO_ENDED` | `{date}` | Акция завершена |
| `PROMO_WRONG_FORMAT` | `{length}` | Неверный формат кода |
| `PROMO_INVALID_CHARS` | — | Недопустимые символы |
| `PROMO_NOT_FOUND` | — | Код не найден |
| `PROMO_ALREADY_USED` | — | Код уже использован |
| `PROMO_DB_ERROR` | — | Ошибка базы данных |
| `PROMO_ACTIVATED` | `{tickets}`, `{total}` | Код успешно активирован |
| `PROMO_ACTIVATION_ERROR` | — | Ошибка активации |

---

### Модуль RECEIPTS

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `UPLOAD_INSTRUCTION` | `{count}` | Инструкция загрузки QR |
| `UPLOAD_QR_PROMPT` | — | Отправьте фото QR |
| `SCANNING` | — | Сканирую QR... |
| `FILE_TOO_BIG` | — | Файл слишком большой |
| `PROCESSING_ERROR` | — | Ошибка обработки |
| `CHECK_FAILED` | — | Не удалось проверить чек |
| `SCAN_FAILED` | — | Не удалось распознать QR |
| `SERVICE_UNAVAILABLE` | — | Сервис недоступен |
| `RECEIPT_NO_PRODUCT` | — | Нет акционных товаров |
| `RECEIPT_DUPLICATE` | — | Чек уже загружен |
| `RECEIPT_FIRST` | — | Поздравляем с первым чеком! |
| `RECEIPT_VALID` | `{count}` | Чек принят |
| `RECEIPT_VALID_TICKETS` | `{new_tickets}`, `{count}` | Чек принят + билеты |
| `PROMO_ENDED` | — | Акция завершена |
| `RATE_LIMIT` | — | Слишком часто, подождите |

---

### Модуль REGISTRATION

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `REG_CANCEL` | — | Регистрация отменена |
| `REG_NAME_ERROR` | — | Ошибка ввода имени |
| `REG_PHONE_PROMPT` | `{name}` | Запрос телефона |
| `REG_PHONE_ERROR` | — | Неверный формат телефона |
| `REG_PHONE_REQUEST` | — | Отправьте номер |
| `REG_SUCCESS` | — | Регистрация завершена |
| `REG_SUCCESS_PROMO` | — | Регистрация завершена (промо) |

---

### Модуль RAFFLE

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `RAFFLE_WIN` | `{prize}` | Уведомление победителю |
| `RAFFLE_LOSE` | — | Уведомление остальным |
| `RAFFLE_INFO` | — | Информация о розыгрышах |

---

### Модуль PROFILE

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `PROFILE_VIEW` | `{name}`, `{phone}`, `{email}` | Просмотр профиля |
| `PROFILE_EDIT_PROMPT` | — | Выберите поле |
| `EDIT_NAME_PROMPT` | — | Введите новое имя |
| `EDIT_PHONE_PROMPT` | — | Введите телефон |
| `EDIT_EMAIL_PROMPT` | — | Введите email |
| `FIELD_UPDATED` | `{field}` | Поле обновлено |
| `REQUIRED_MISSING` | `{field}` | Обязательное поле не заполнено |
| `CANCEL` | — | Отменено |

---

### Модуль BROADCAST

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `BROADCAST_START` | `{count}` | Начало рассылки |
| `BROADCAST_PREVIEW` | — | Предпросмотр |
| `BROADCAST_CONFIRM` | — | Подтверждение |
| `BROADCAST_SCHEDULE` | — | Когда отправить? |
| `BROADCAST_SCHEDULED` | `{id}`, `{time}` | Рассылка запланирована |
| `BROADCAST_STARTED` | `{id}` | Рассылка начнётся |
| `BROADCAST_CANCELLED` | — | Рассылка отменена |
| `INVALID_DATE` | — | Неверная дата |

---

### Модуль STATISTICS

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `STATS_TITLE` | — | Заголовок статистики |
| `STATS_USERS` | — | Пользователи |
| `STATS_ACTIVATIONS` | — | Активации |
| `STATS_TICKETS` | `{count}` | Билетов в системе |
| `STATS_CODES` | `{count}` | Промокодов осталось |

---

### Модуль ADMIN

| Ключ | Плейсхолдеры | Описание |
|------|--------------|----------|
| `STATS_MSG` | `{users}`, `{users_today}`, `{receipts}`, `{valid}`, `{receipts_today}`, `{participants}`, `{conversion}`, `{winners}` | Статистика для админа |

---

## 4. Регистрация в БД

```sql
-- Проверить что manifest_path заполнен:
SELECT id, name, manifest_path FROM bot_registry WHERE is_active = true;

-- Если пусто — обновить:
UPDATE bot_registry SET manifest_path = '/path/to/bots/my_bot' WHERE id = ?;
```

---

## 5. Настройки модулей (settings_schema)

### registration
- `subscription_required` — требовать подписку на канал
- `subscription_channel_id` — ID канала (-100...)
- `subscription_channel_url` — ссылка на канал

### profile
- `fields` — поля профиля (name,phone,email)
- `required_fields` — обязательные поля

### receipts
- `target_keywords` — ключевые слова товаров
- `excluded_keywords` — исключения

---

## 6. Чек-лист перед запуском

- [ ] `manifest.json` создан с правильными `modules`
- [ ] `content.py` содержит ВСЕ ключи из используемых модулей
- [ ] `manifest_path` заполнен в `bot_registry`
- [ ] Токен бота добавлен в панель
- [ ] База данных создана
- [ ] Промо-коды загружены (если promo-бот)
- [ ] Настройки модулей проверены в панели
- [ ] Протестирован `/start` с новым и существующим пользователем
- [ ] Протестирован FAQ
- [ ] Протестирована основная механика (промо/чеки)

---

## 7. Типичные проблемы

| Проблема | Решение |
|----------|---------|
| Дефолтные тексты вместо кастомных | Проверить `manifest_path` в БД |
| `None` в билетах | Исправлено в handlers.py (or 0) |
| FAQ показывает дефолт | Добавить `FAQ_*` ключи в content.py |
| Бот не отвечает на /start | Проверить токен и `is_active` в БД |
| Ошибка "not initialized" | Убедиться что `config_manager.load()` вызывается |
