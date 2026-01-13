# Broadcast Module

Модуль рассылки сообщений пользователям.

## Зависимости

- `core` — для админ-команд

## Описание

Позволяет отправлять сообщения пользователям через админ-панель или бота.
Поддерживает текст, фото, видео, inline-кнопки и отложенную отправку.

---

## Способы запуска

| Способ | Описание |
|--------|----------|
| Админ-панель | Полный UI с превью |
| Бот (команда) | `/broadcast` для быстрых рассылок |

---

## Возможности

### Контент
- ✅ Текст (с форматированием)
- ✅ Фото
- ✅ Видео
- ✅ Inline-кнопки (ссылки, callback)

### Аудитория
- Все пользователи
- Ручной выбор (список user_id)
- По фильтрам (в будущем)

### Время отправки
- Сейчас (мгновенно)
- Запланировать на дату/время

---

## Процесс рассылки (Админ-панель)

### Шаг 1: Создание
| Поле | Тип | Описание |
|------|-----|----------|
| Текст | textarea | Сообщение с форматированием |
| Медиа | file | Фото или видео |
| Кнопки | builder | Добавить inline-кнопки |
| Аудитория | select | Все / Вручную |
| Время | datetime | Сейчас / Запланировать |

### Шаг 2: Превью
- Показывает как будет выглядеть сообщение

### Шаг 3: Отправка
- Кнопка "Отправить" / "Запланировать"

---

## Edge Cases

### Бот упал во время рассылки
- Сохраняем прогресс в БД
- При перезапуске продолжаем с места остановки

### Пользователь заблокировал бота
- Статус `blocked`
- Статистика учитывает

### Отмена запланированной рассылки
- Можно отменить до начала отправки

---

## Статистика рассылки

| Метрика | Описание |
|---------|----------|
| Всего | Целевая аудитория |
| Отправлено | Успешно доставлено |
| Заблокировали | Бот заблокирован |
| В процессе | Ещё отправляется |

---

## Handlers (бот)

| Trigger | Handler | Description |
|---------|---------|-------------|
| `/broadcast` | `start_broadcast` | Начать рассылку (только админы) |
| Text/Photo/Video (в режиме) | `receive_content` | Получить контент |
| `callback:broadcast_*` | `broadcast_actions` | Подтверждение/отмена |

---

## База данных

### Таблица `broadcasts`
```sql
CREATE TABLE broadcasts (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    media_type VARCHAR(20),     -- photo, video, null
    media_path TEXT,
    buttons JSONB,              -- inline buttons config
    audience VARCHAR(20) DEFAULT 'all',
    audience_ids INT[],         -- для ручного выбора
    scheduled_at TIMESTAMP,     -- null = сейчас
    status VARCHAR(20) DEFAULT 'pending',
    total_count INT DEFAULT 0,
    sent_count INT DEFAULT 0,
    blocked_count INT DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_by INT,             -- admin user id
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Таблица `broadcast_log`
```sql
CREATE TABLE broadcast_log (
    id SERIAL PRIMARY KEY,
    broadcast_id INT REFERENCES broadcasts(id),
    user_id INT REFERENCES users(id),
    status VARCHAR(20),         -- sent, blocked, failed
    sent_at TIMESTAMP DEFAULT NOW()
);
```

---

## Статусы рассылки

| Статус | Описание |
|--------|----------|
| `pending` | Создана, редактируется |
| `scheduled` | Запланирована на время |
| `in_progress` | Отправляется |
| `completed` | Завершена |
| `cancelled` | Отменена |

---

## События

### Испускает
- `broadcast.started` — `{ broadcast_id, total }`
- `broadcast.completed` — `{ broadcast_id, sent, blocked }`

---

## Интеграция с панелью

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/broadcasts` | GET | Список рассылок |
| `/api/broadcasts` | POST | Создать рассылку |
| `/api/broadcasts/{id}` | GET | Детали и статистика |
| `/api/broadcasts/{id}/send` | POST | Запустить рассылку |
| `/api/broadcasts/{id}/cancel` | POST | Отменить |
