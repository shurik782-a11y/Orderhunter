# OrderHunter

Бот мониторинга фриланс-заказов для РФ (режим **Assist**): сбор с Telegram / FL.ru / Kwork → матчинг по вашему профилю → черновик отклика → уведомление в Telegram с кнопками.

## Структура

```
OrderHunter/
├── config/           profile.yaml, portfolio.json, telegram-channels.yaml
├── docs/             REGISTRATION.md — чеклист регистрации на площадках
├── backend/          FastAPI + aiogram + worker + PostgreSQL
├── mtproto-worker/   GramJS — мониторинг TG-каналов
└── docker-compose.yml
```

## Deploy (Railway)

Репозиторий: https://github.com/shurik782-a11y/Orderhunter

1. Два сервиса + Postgres — см. [`docs/RAILWAY.md`](docs/RAILWAY.md)
2. Шпаргалка Variables: [`docs/RAILWAY_VARIABLES.md`](docs/RAILWAY_VARIABLES.md)

| Сервис | Dockerfile |
|--------|------------|
| API + worker + notify-bot | `backend/Dockerfile` |
| GramJS channel monitor | `mtproto-worker/Dockerfile` (регион **US**) |

## Быстрый старт (локально)

### 1. PostgreSQL

```bash
cd OrderHunter
docker compose up -d
```

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Заполните BOT_TOKEN, ADMIN_TELEGRAM_IDS, INTERNAL_API_SECRET, LLM_*
uvicorn app.main:app --reload --port 8000
```

В отдельном терминале — notify-бот:

```bash
python -m app.bot.runner
```

### 3. MTProto worker (Telegram-каналы)

```bash
cd mtproto-worker
cp .env.example .env
npm install
npm run telegram:login
npm run dev
```

`INTERNAL_API_SECRET` должен совпадать в backend и mtproto-worker.

### 4. FL.ru / Kwork

В `backend/.env`:

```
FL_RU_ENABLED=true
FL_RU_LOGIN=...
FL_RU_PASSWORD=...

KWORK_ENABLED=true
KWORK_LOGIN=...
KWORK_PASSWORD=...
```

Playwright (один раз):

```bash
playwright install chromium
```

## Assist UI

На каждую подходящую заявку приходит карточка:

- **Отправить** — отметить отправленным, опционально лид в Handler
- **Kwork отклик** — `submit_offer` через API (после Approve)
- **Править** — прислать новый текст
- **Пропустить**
- **Открыть** — ссылка на заказ

## API

| Endpoint | Описание |
|----------|----------|
| `GET /health` | Health check |
| `GET /analytics/funnel` | Воронка метрик |
| `POST /internal/telegram/ingest` | Приём постов от mtproto-worker |

## Конфигурация профиля

- [`config/profile.yaml`](config/profile.yaml) — скиллы, стоп-слова, пороги
- [`config/portfolio.json`](config/portfolio.json) — кейсы для матчинга и LLM

## Регистрация на площадках

См. [`docs/REGISTRATION.md`](docs/REGISTRATION.md).

## Handler CRM

```
HANDLER_LEADS_ENABLED=true
HANDLER_LEADS_URL=http://localhost:3000/api/leads
```

При нажатии «Отправить» создаётся лид с описанием заказа и черновиком.
