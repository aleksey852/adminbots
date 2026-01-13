# Registration Module

Модуль регистрации пользователей с опциональной проверкой подписки на канал.

## Зависимости

- `core` — для обработки /start

## Описание

Регистрирует новых пользователей в базе данных при первом взаимодействии с ботом. 
Опционально требует подписку на Telegram-канал перед использованием бота.

## Handlers

| Trigger | Handler | Description |
|---------|---------|-------------|
| `/start` (после core) | `register_user` | Регистрация нового пользователя |
| `callback:check_subscription` | `check_subscription` | Проверка подписки на канал |

## Настройки

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `subscription_required` | checkbox | false | Требовать подписку на канал |
| `subscription_channel_id` | text | | ID канала (с минусом, например -1001234567890) |
| `subscription_channel_name` | text | | Отображаемое имя канала |
| `referral_enabled` | checkbox | false | Включить реферальную систему |

## База данных

### Таблицы
- `users` — основная таблица пользователей (создаётся при инициализации бота)

### Методы
- `add_user(telegram_id, username, full_name, source)` — регистрация
- `get_user(telegram_id)` — получение пользователя
- `update_user(telegram_id, **fields)` — обновление

## События

### Испускает
- `registration.user_registered` — `{ user_id, telegram_id, source }` — новый пользователь
- `registration.subscription_verified` — `{ user_id }` — подписка подтверждена

### Слушает
- `core.user_started` — инициирует проверку регистрации

## Сообщения

| Key | Description |
|-----|-------------|
| `subscription_required` | Текст с просьбой подписаться |
| `subscription_button` | Текст кнопки "Подписаться" |
| `check_subscription_button` | Текст кнопки "Я подписался" |
| `subscription_success` | Сообщение после успешной подписки |
| `subscription_failed` | Сообщение если не подписан |
