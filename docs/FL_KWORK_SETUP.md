# Подключение FL.ru и Kwork (после регистрации)

## 1. Дозаполнить профили (5–10 мин)

### FL.ru
- Специализации: программирование / веб / боты
- 2–3 работы в портфолио (Jummy, BeardNuts, Parfumistery)
- Уведомления → раздел «Программирование»

### Kwork
- Минимум 2–3 активных кворка (бот / магазин / FastAPI)
- Включить **Биржу проектов** и купить/иметь **коннекты** (нужны для отклика)

## 2. Variables на Railway → `orderhunter-api`

Добавьте / измените:

```
FL_RU_ENABLED=true
FL_RU_LOGIN=ваш_логин_или_email
FL_RU_PASSWORD=ваш_пароль
FL_RU_POLL_INTERVAL_SECONDS=300
FL_RU_CATEGORY_URL=https://www.fl.ru/projects/category/programmirovanie/

KWORK_ENABLED=true
KWORK_LOGIN=email_или_логин_kwork
KWORK_PASSWORD=пароль_kwork
KWORK_POLL_INTERVAL_SECONDS=300
```

Redeploy `orderhunter-api`.

## 3. Что ожидать в логах

```
Kwork auth ok
Kwork baseline done (... projects marked seen)
FL.ru baseline done (... projects marked seen)
```

Первый прогон **не шлёт** старые заказы — только помечает. Новые появятся через 5–10 мин.

## 4. Как откликаться (Assist)

Карточка в @OrHu_bot:

| Кнопка | FL.ru | Kwork |
|--------|-------|-------|
| **Открыть** | страница заказа → вставить черновик вручную | то же |
| **Отправить** | отметить у себя как отправленный | то же |
| **Kwork отклик** | — | отправка через API (тратит 1 connect) |
| **Править** | новый текст одним сообщением | то же |
| **Пропустить** | скрыть | скрыть |

На FL.ru автоотправку формы не делаем (ToS) — только черновик + ссылка.

## 5. Если в логах ошибка

| Лог | Действие |
|-----|----------|
| `Kwork auth failed` | проверить логин/пароль; иногда нужен email, не ник |
| `Kwork poll failed` | подождать / смотреть текст error |
| `FL.ru poll failed` | часто капча/вёрстка; мониторинг публичной ленты может работать и без логина |
| `Daily draft limit` | лимит на день; завтра или поднять `max_drafts_per_day` в `config/profile.yaml` |

## 6. Проверка

В боте: `/stats` — должны расти `seen` / `matched` / `notified` с источниками fl_ru и kwork.
