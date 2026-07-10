# Railway — OrderHunter

Нужны **2 сервиса** + **PostgreSQL** в одном Railway-проекте.

| Сервис | Root Directory | Dockerfile Path | Регион |
|--------|----------------|-----------------|--------|
| `orderhunter-api` | *(пусто / repo root)* | `backend/Dockerfile` | любой |
| `orderhunter-mtproto` | *(пусто / repo root)* | `mtproto-worker/Dockerfile` | **US** (MTProto) |
| Postgres | Add Plugin → PostgreSQL | — | тот же проект |

---

## 1. Сервис `orderhunter-api` — Variables

Скопируйте в Railway → Variables. `DATABASE_URL` обычно подставляется сам после Add Plugin → PostgreSQL (Reference).

### Обязательные

| Variable | Значение | Комментарий |
|----------|----------|-------------|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Reference на плагин Postgres |
| `BOT_TOKEN` | токен от @BotFather | notify-бот Assist |
| `ADMIN_TELEGRAM_IDS` | ваш numeric Telegram ID | можно несколько через запятую |
| `INTERNAL_API_SECRET` | длинная случайная строка | **тот же** секрет, что у mtproto |
| `CONFIG_DIR` | `/app/config` | путь внутри Docker-образа |

### LLM (рекомендуется)

| Variable | Пример | Комментарий |
|----------|--------|-------------|
| `LLM_ENABLED` | `true` | `false` = только шаблонные отклики |
| `LLM_API_KEY` | `sk-...` | DeepSeek / OpenRouter |
| `LLM_BASE_URL` | `https://api.deepseek.com` | |
| `LLM_MODEL` | `deepseek-chat` | |

### Площадки (после регистрации)

| Variable | Старт | Позже |
|----------|-------|-------|
| `FL_RU_ENABLED` | `false` | `true` |
| `FL_RU_LOGIN` | — | логин FL.ru |
| `FL_RU_PASSWORD` | — | пароль FL.ru |
| `FL_RU_POLL_INTERVAL_SECONDS` | `300` | |
| `KWORK_ENABLED` | `false` | `true` |
| `KWORK_LOGIN` | — | |
| `KWORK_PASSWORD` | — | |
| `KWORK_POLL_INTERVAL_SECONDS` | `300` | |

### Опционально

| Variable | Значение |
|----------|----------|
| `WORKER_ENABLED` | `true` |
| `HANDLER_LEADS_ENABLED` | `false` → `true` когда Handler на проде |
| `HANDLER_LEADS_URL` | `https://<handler-domain>/api/leads` |
| `PORT` | Railway ставит сам; в Dockerfile уже `${PORT}` |

**Не задавайте вручную** `DATABASE_URL_SYNC` — backend сам нормализует `DATABASE_URL` под asyncpg.

---

## 2. Сервис `orderhunter-mtproto` — Variables

| Variable | Значение | Комментарий |
|----------|----------|-------------|
| `TELEGRAM_API_ID` | с https://my.telegram.org | |
| `TELEGRAM_API_HASH` | с my.telegram.org | |
| `TELEGRAM_USER_SESSION` | строка после `npm run telegram:login` | **секрет** |
| `ORDERHUNTER_BACKEND_URL` | `https://<orderhunter-api>.up.railway.app` | публичный URL API-сервиса |
| `INTERNAL_API_SECRET` | **тот же**, что у api | |
| `CHANNELS_CONFIG` | `/app/config/telegram-channels.yaml` | |
| `POLL_INTERVAL_SECONDS` | `90` | |
| `TELEGRAM_PROXY_URL` | *(пусто на US)* | SOCKS5 только если DC недоступны |

---

## 3. Настройки сервисов в UI Railway

### orderhunter-api
1. New Project → Deploy from GitHub → `shurik782-a11y/Orderhunter`
2. Settings → Root Directory: **оставьте пустым**
3. Settings → Dockerfile Path: `backend/Dockerfile`
4. Add Plugin → **PostgreSQL**
5. Variables → вставьте таблицу выше
6. Generate Domain (нужен для `ORDERHUNTER_BACKEND_URL`)

### orderhunter-mtproto
1. В том же проекте: New Service → GitHub → тот же репо
2. Root Directory: **пусто**
3. Dockerfile Path: `mtproto-worker/Dockerfile`
4. Region: **US West / US East** (как Jerome)
5. Variables → таблица mtproto
6. Restart после того, как api получил публичный URL

---

## 4. Проверка

```text
GET https://<orderhunter-api>.up.railway.app/health
→ {"status":"ok","service":"orderhunter"}

GET https://<orderhunter-api>.up.railway.app/analytics/funnel
```

В Telegram напишите боту `/start` и `/stats`.

---

## 5. Секреты — не коммитить

- `BOT_TOKEN`, `TELEGRAM_USER_SESSION`, `INTERNAL_API_SECRET`
- `FL_RU_*`, `KWORK_*`, `LLM_API_KEY`
