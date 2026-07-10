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

## Сервис 2: `orderhunter-mtproto` (регион US)

```
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_USER_SESSION=
ORDERHUNTER_BACKEND_URL=https://ВАШ-API.up.railway.app
INTERNAL_API_SECRET=
CHANNELS_CONFIG=/app/config/telegram-channels.yaml
POLL_INTERVAL_SECONDS=90
```

`INTERNAL_API_SECRET` — одинаковый в обоих сервисах.
Полная инструкция: [RAILWAY.md](RAILWAY.md)
