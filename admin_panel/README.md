# Admin Panel API

REST API для управления ботами.

## Аутентификация

Все запросы требуют сессионной авторизации (cookie-based).

---

## Ответы API

### Успешный ответ
```json
{
  "success": true,
  "data": { ... },
  "message": "Operation completed"
}
```

### Ошибка
```json
{
  "success": false,
  "message": "Error description",
  "errors": ["detail1", "detail2"]
}
```

---

## Роутеры

### `/auth` — Авторизация
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/login` | Страница входа |
| POST | `/login` | Авторизация |
| GET | `/logout` | Выход |

### `/bots` — Управление ботами
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Список ботов |
| POST | `/create` | Создать бота |
| GET | `/{id}` | Детали бота |
| POST | `/{id}/update` | Обновить бота |
| POST | `/{id}/delete` | Удалить бота |
| POST | `/{id}/restart` | Перезапустить |

### `/users` — Пользователи
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Список пользователей |
| GET | `/{id}` | Детали пользователя |
| POST | `/{id}/block` | Заблокировать |
| POST | `/{id}/tickets` | Начислить билеты |

### `/campaigns` — Рассылки и розыгрыши
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Список кампаний |
| POST | `/broadcast` | Создать рассылку |
| POST | `/raffle` | Создать розыгрыш |
| POST | `/{id}/cancel` | Отменить |

### `/content` — Промокоды и чеки
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/codes` | Список промокодов |
| POST | `/codes/upload` | Загрузить CSV |
| GET | `/receipts` | Список чеков |
| POST | `/receipts/{id}/approve` | Одобрить чек |

### `/texts` — Тексты бота
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Все тексты |
| POST | `/save` | Сохранить текст |

### `/system` — Система
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/logs` | Логи системы |
| GET | `/backups` | Список бэкапов |
| POST | `/backup` | Создать бэкап |

---

## Использование в коде

```python
from admin_panel.utils.responses import success, error, not_found

@router.get("/api/items")
async def get_items():
    items = await fetch_items()
    return success(data=items)

@router.post("/api/items")
async def create_item(data: ItemCreate):
    try:
        item = await create(data)
        return success(data=item, message="Created")
    except ValidationError as e:
        return error("Validation failed", errors=e.messages)
```
