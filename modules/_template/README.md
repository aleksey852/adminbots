# Module Template

Шаблон для создания новых модулей.

## Quick Start

```bash
cp -r modules/_template modules/my_module
```

## Files

| File | Required | Purpose |
|------|----------|---------|
| `__init__.py` | ✅ | Exports module instance |
| `README.md` | ✅ | Documentation |
| `handlers.py` | ✅ | Aiogram handlers |
| `db/methods.py` | ❌ | Database operations |
| `api/routes.py` | ❌ | Admin panel API |

## Checklist

- [ ] Rename class and `name` field
- [ ] Update version and description
- [ ] Implement handlers in `_setup_handlers`
- [ ] Write README documentation
- [ ] Add to manifest.json if using with custom bot
