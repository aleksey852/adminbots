# UPGRADE NOTIFY - Admin Bots Platform

Инструкции по обновлению платформы.

## Быстрое обновление

```bash
cd /opt/admin-bots-platform
sudo bash scripts/update.sh
```

## Ручное обновление

### 1. Бэкап

```bash
sudo bash /opt/admin-bots-platform/scripts/backup.sh
```

### 2. Обновление кода

```bash
cd /opt/admin-bots-platform
git pull origin main
```

### 3. Зависимости

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Перезапуск

```bash
sudo systemctl restart admin_bots
sudo systemctl restart admin_panel
```

### 5. Проверка

```bash
sudo journalctl -u admin_bots -f
sudo journalctl -u admin_panel -f
```

## Диагностика

### Проверка сервисов

```bash
sudo systemctl status admin_bots
sudo systemctl status admin_panel
```

### Логи

```bash
sudo journalctl -u admin_bots -n 100
sudo journalctl -u admin_panel -n 100
```

### База данных

```bash
sudo -u postgres psql admin_bots -c "SELECT 1;"
```

## Откат

Если что-то пошло не так:

```bash
# Остановить сервисы
sudo systemctl stop admin_bots admin_panel

# Восстановить бэкап
gunzip -c /var/backups/admin-bots-platform/backup_YYYYMMDD_HHMMSS.sql.gz | sudo -u postgres psql admin_bots

# Запустить сервисы
sudo systemctl start admin_bots admin_panel
```

## Поддержка

Если проблема не решается:

```bash
# Собрать логи
sudo journalctl -u admin_bots -n 200 > bot_logs.txt
sudo journalctl -u admin_panel -n 200 > admin_logs.txt
```

Отправьте логи в [GitHub Issues](https://github.com/aleksey852/adminbots/issues).
