# Admin Bots Framework — Architecture

> **Version**: 3.0  
> **Status**: Production-ready framework for Telegram bots

## Overview

Admin Bots — это **фреймворк для создания и управления Telegram-ботами** через единую админ-панель. Архитектура построена по принципу **mega-app**: стабильное ядро + подключаемые модули.

```
┌─────────────────────────────────────────────────────┐
│                   Admin Panel (UI)                  │
├─────────────────────────────────────────────────────┤
│                    API Layer                        │
├──────────┬──────────┬──────────┬───────────────────┤
│  Module  │  Module  │  Module  │   ... N modules   │
│  Promo   │ Receipts │  Raffle  │                   │
├──────────┴──────────┴──────────┴───────────────────┤
│                 CORE (Framework)                    │
│   • Module Loader    • Event Bus                   │
│   • Database Layer   • Config Manager              │
│   • Bot Manager      • Message Router              │
├─────────────────────────────────────────────────────┤
│              Infrastructure (DB, Redis)             │
└─────────────────────────────────────────────────────┘
```

---

## Core Principles

### 1. Plugin-First Design
Ядро не знает о конкретных модулях. Новый модуль = новая папка, без правок в core.

### 2. Module Contract
Каждый модуль реализует чёткий интерфейс: metadata, handlers, settings, migrations.

### 3. Configuration over Code
Большинство настроек — через UI админки, не через код.

### 4. Isolation
Модули не импортируют друг друга напрямую. Коммуникация через Event Bus.

---

## Directory Structure

```
adminbots/
├── core/                   # Framework core (DO NOT MODIFY for bots)
│   ├── module_base.py      # BotModule base class
│   ├── module_loader.py    # Auto-discovery
│   ├── event_bus.py        # Inter-module communication
│   ├── config.py           # System-only config
│   └── database/           # Connection pool, migrations
│
├── modules/                # Pluggable modules
│   ├── _template/          # Template for new modules
│   ├── core/               # Base functionality (menu, profile)
│   ├── registration/       # User registration
│   ├── promo/              # Promo codes
│   ├── receipts/           # Receipt processing
│   └── raffle/             # Raffles
│
├── admin_panel/            # Web interface
├── bots/                   # Bot configurations (manifest.json)
└── docs/                   # Documentation
```

---

## Module Contract

See [MODULE_DEVELOPMENT.md](./MODULE_DEVELOPMENT.md) for full specification.

### Required Files

| File | Purpose |
|------|---------|
| `__init__.py` | Exports module instance |
| `README.md` | Documentation |
| `handlers.py` | Aiogram handlers |

### Optional Files

| File | Purpose |
|------|---------|
| `db/methods.py` | Database operations |
| `db/migrations.sql` | Table definitions |
| `api/routes.py` | Admin panel routes |
| `schemas.py` | Pydantic models |

---

## See Also

- [QUICKSTART.md](./QUICKSTART.md) — Create your first bot
- [MODULE_DEVELOPMENT.md](./MODULE_DEVELOPMENT.md) — Build a module
- [API.md](./API.md) — Admin panel API reference
