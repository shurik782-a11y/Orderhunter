# Railway Variables — шпаргалка

## Сервис 1: `orderhunter-api`

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
BOT_TOKEN=
ADMIN_TELEGRAM_IDS=
INTERNAL_API_SECRET=
CONFIG_DIR=/app/config
LLM_ENABLED=true
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
WORKER_ENABLED=true
FL_RU_ENABLED=false
KWORK_ENABLED=false
HANDLER_LEADS_ENABLED=false
```

Bool-переменные: только `true` / `false`, либо удалите Variable.  
Пустая строка (`FL_RU_ENABLED=`) раньше роняла API — в коде это уже обработано.

## Сервис 2: `orderhunter-mtproto` (регион US)

**Без этих трёх переменных сервис будет рестартиться с ошибкой
`API ID or Hash cannot be empty`:**

```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789
TELEGRAM_USER_SESSION=1BQgb...длинная_строка_после_login...
ORDERHUNTER_BACKEND_URL=https://ВАШ-API.up.railway.app
INTERNAL_API_SECRET=
CHANNELS_CONFIG=/app/config/telegram-channels.yaml
POLL_INTERVAL_SECONDS=90
```

Как получить:
1. https://my.telegram.org → API development tools → `api_id` + `api_hash`
2. Локально: `cd mtproto-worker && cp .env.example .env` → вписать id/hash → `npm run telegram:login`
3. Скопировать `TELEGRAM_USER_SESSION` из вывода в Railway Variables

`INTERNAL_API_SECRET` — одинаковый в обоих сервисах.
Полная инструкция: [RAILWAY.md](RAILWAY.md)
