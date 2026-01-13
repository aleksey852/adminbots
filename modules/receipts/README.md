# Receipts Module

Модуль загрузки и проверки кассовых чеков.

## Зависимости

- `core` — главное меню
- `registration` — пользователь должен быть зарегистрирован
- `profile` — проверка обязательных полей (опционально)

## Описание

Пользователь загружает фото QR-кода чека. Модуль проверяет чек через ProverkaCheka API,
валидирует товары по ключевым словам и начисляет билеты.

---

## Handlers

| Trigger | Handler | Description |
|---------|---------|-------------|
| `🧾 Загрузить чек` | `start_receipt_upload` | Начать загрузку |
| `🧾 Ещё чек` | `start_receipt_upload` | Загрузить ещё |
| Photo (в состоянии) | `process_receipt_photo` | Обработка фото |
| Text (в состоянии) | `process_receipt_invalid_type` | Подсказка или отмена |

---

## Настройки

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `target_keywords` | textarea | `чипсы,buster,vibe` | Ключевые слова товаров |
| `excluded_keywords` | textarea | | Исключённые слова |

---

## База данных

### Таблица `receipts`
```sql
CREATE TABLE receipts (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    status VARCHAR(20) DEFAULT 'pending',
    raw_qr TEXT,
    fiscal_drive_number VARCHAR(50),
    fiscal_document_number VARCHAR(50),
    fiscal_sign VARCHAR(50),
    total_sum INT,
    tickets INT DEFAULT 1,
    product_name TEXT,
    data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(fiscal_drive_number, fiscal_document_number, fiscal_sign)
);
```

---

## События

### Испускает
- `receipts.receipt_approved` — `{ user_id, tickets, product }`

---

## Сообщения (content.py)

| Key | Description |
|-----|-------------|
| `upload_instruction` | Инструкция по загрузке |
| `scanning` | Сканирую QR... |
| `receipt_valid` | Чек принят |
| `receipt_no_product` | Нет акционных товаров |
| `receipt_duplicate` | Чек уже загружен |
| `scan_failed` | Не удалось распознать |

---

## Внешние API

- **ProverkaCheka** — проверка чеков через ФНС API
- Токен: `PROVERKA_CHEKA_TOKEN` в config.py
