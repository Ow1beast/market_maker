# Binance Market Maker Bot (Docker)

Универсальный маркет-мейкер бот для Binance Spot и Futures с поддержкой:
- WebSocket стакана
- PnL-трекинг через SQLite
- Telegram-уведомлений и команд
- Stop-loss / Take-profit
- Запуска через Docker Compose

---

## Установка на сервер (AWS EC2 / Linux 2)

### 1. Установи Docker и Docker Compose

```bash
sudo yum update -y
sudo yum install -y docker git
sudo service docker start
sudo usermod -aG docker $USER
newgrp docker

sudo curl -L https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m) \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

---

### 2. Клонируй проект или распакуй архив

```bash
unzip market_maker_docker.zip
cd market_maker_docker
```

---

### 3. Настрой `.env`

```bash
nano .env
```
Укажи API ключи, режим `TRADE_MODE=spot` или `futures`, лимиты и токен Telegram-бота.

---

### 4. Запуск через Docker

```bash
docker-compose up -d --build
```

Логи пишутся в папку `logs/`

---

### 5. Telegram команды

| Команда        | Назначение                          |
|----------------|--------------------------------------|
| `/status`      | Проверка работоспособности бота      |
| `/pnl_today`   | PnL и количество сделок за сегодня   |
| `/pnl_table`   | Таблица прибыли по дням (7 дней)     |
| `/restart`     | Перезапуск через systemctl           |

---

## Структура проекта

```bash
market_maker_docker/
├── main_bot.py
├── db.py
├── bot_commands.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env
└── logs/
```

---

### Поддержка
Если нужно добавить график, автоперенос PnL в Excel или веб-интерфейс — пишите.
