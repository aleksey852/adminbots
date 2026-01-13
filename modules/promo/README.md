# Promo Module

Модуль активации промокодов.

## Зависимости

- `core` — главное меню
- `profile` — проверка обязательных полей

## Описание

Пользователь вводит промокод → получает билеты для розыгрыша.
Коды загружаются через админ-панель (CSV или вручную).

## Бизнес-логика

- **Источник кодов:** загрузка CSV/вручную в панели
- **Лимиты:** без лимитов (сколько кодов — столько активаций)
- **Номинал:** все коды = 1 билет (настраивается глобально)
- **Срок действия:** бессрочные (пока акция активна)
- **Выдача:** через бота + печатные

## Handlers

| Trigger | Handler | Description |
|---------|---------|-------------|
| `🔑 Ввести промокод` | `promo_prompt` | Показывает инструкцию |
| Text (12 символов) | `process_promo_code` | Валидация и активация |
| `callback:activate_code:*` | `activate_code_callback` | Активация через inline-кнопку |

## Кнопка меню

```python
menu_buttons = [
    {"text": "🔑 Ввести промокод", "order": 20}
]
```

## Настройки

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `code_length` | number | 12 | Длина промокода |
| `tickets_per_code` | number | 1 | Билетов за активацию |

## База данных

### Таблица `promo_codes`
```sql
CREATE TABLE promo_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'active',  -- active, used
    user_id INT REFERENCES users(id),
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Методы
- `get_promo_code(code)` → PromoCode | None
- `use_promo_code(code_id, user_id)` → bool
- `import_codes(codes: List[str])` → int (count imported)

## События

### Испускает
- `promo.code_activated` — `{ user_id, code, tickets }`

## Интеграция с Profile

Перед активацией проверяет `required_fields`:
```python
if not await profile_module.check_required(user_id, bot_id):
    await profile_module.request_required_fields(message, bot_id)
    return
```

## Интеграция с панелью

- `GET /api/promo/codes` — список кодов
- `POST /api/promo/import` — импорт CSV
- `POST /api/promo/send` — выдать код пользователю
- `DELETE /api/promo/codes/{id}` — удалить код
