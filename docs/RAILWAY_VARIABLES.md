# Railway Variables — шпаргалка

## Сервис 1: `orderhunter-api`

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
BOT_TOKEN=
ADMIN_TELEGRAM_IDS=
INTERNAL_API_SECRET=
CONFIG_DIR=/app/config
LLM_ENABLED=true
LLM_API_KEY=sk-or-v1-ВАШ_КЛЮЧ
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=deepseek/deepseek-chat
WORKER_ENABLED=true
FL_RU_ENABLED=false
KWORK_ENABLED=false
FREELANCE_RU_ENABLED=false
FREELANCEHUNT_ENABLED=false
WORKSPACE_RU_ENABLED=false
HANDLER_LEADS_ENABLED=false
```

После включения площадок (Assist: карточка → Открыть → вставить черновик):

```
FL_RU_ENABLED=true
FL_RU_LOGIN=
FL_RU_PASSWORD=
KWORK_ENABLED=true
KWORK_LOGIN=
KWORK_PASSWORD=
FREELANCE_RU_ENABLED=true
FREELANCE_RU_SEARCH_URL=https://freelance.ru/project/search?q=python
FREELANCEHUNT_ENABLED=true
FREELANCEHUNT_PROJECTS_URL=https://freelancehunt.com/projects/skill/veb-programmirovanie/99.html
WORKSPACE_RU_ENABLED=true
WORKSPACE_RU_PROJECTS_URL=https://workspace.ru/tenders/web-development/
```

**Очередь карточек:** в чат уходит **одна** активная; остальные ждут в «Очередь».  
Если «активная есть», а сообщения нет — Очередь → «Повторить» или «Пропуск → следующая».  
NOTIFIED старше 2ч снимаются автоматически.

**OpenRouter:** ключ `sk-or-...` + `LLM_BASE_URL=https://openrouter.ai/api/v1` + модель вида `deepseek/deepseek-chat`.  
Если оставить `api.deepseek.com` с ключом OpenRouter — будет **401**.

Bool-переменные: только `true` / `false`, либо удалите Variable.  
Пустая строка (`FL_RU_ENABLED=`) раньше роняла API — в коде это уже обработано.

**Conflict getUpdates / двойные ответы:** у `orderhunter-api` должна быть **1 replica**.  
В коде есть Postgres leader-lock на polling, но лучше всё равно держать 1 реплику. Не запускайте бота локально с тем же `BOT_TOKEN`.

## Сервис 2: `orderhunter-mtproto` (регион US)

**Replicas = 1** на один session-string.

Telegram **нельзя** подключить одну и ту же `TELEGRAM_USER_SESSION` в двух местах (`AUTH_KEY_DUPLICATED`).

Нужны два места (Railway + локально / второй сервер) — сделайте **два логина** (тот же аккаунт, две разные session-строки):

```bash
cd mtproto-worker
npm run telegram:login
# → SESSION_A в Railway

# второй раз (новое устройство/сессия):
npm run telegram:login
# → SESSION_B локально или во второй сервис
```

Один аккаунт — ок. Одна и та же строка session — нет.

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

**Подпишитесь session-аккаунтом** на каналы из `config/telegram-channels.yaml` с `enabled: true`, в т.ч.:
`progjob`, `freelance_vakansiii`, `IT_Outstaff_projects`, `forwebdev`, `js_jobs`, `frontend_jobs`, `backend_jobs`, `devschat`
(+ уже рабочие: `freelance_orders`, `frwork3`, `allw0rk`, …).
Невалидные username в логах будут `skip`, без crash.

Как получить:
1. https://my.telegram.org → API development tools → `api_id` + `api_hash`
2. Локально: `cd mtproto-worker && cp .env.example .env` → вписать id/hash → `npm run telegram:login`
3. Скопировать `TELEGRAM_USER_SESSION` из вывода в Railway Variables

`INTERNAL_API_SECRET` — одинаковый в обоих сервисах.
Полная инструкция: [RAILWAY.md](RAILWAY.md)
