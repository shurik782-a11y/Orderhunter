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

В чат приходит **одна** карточка. Остальные ждут в «Очередь». После Отправить / Пропуск / Kwork — сразу следующая.

| Кнопка | FL.ru / Freelance.ru / Freelancehunt | Kwork |
|--------|--------------------------------------|-------|
| **Открыть** | страница заказа → вставить черновик вручную | то же |
| **Отправить** | отметить у себя как отправленный → next | то же |
| **Kwork отклик** | — | отправка через API (тратит 1 connect) |
| **Править** | новый текст одним сообщением | то же |
| **Пропустить** | скрыть → next | скрыть → next |

Автоотправку формы на FL / Freelance.ru / Freelancehunt не делаем (ToS) — только черновик + ссылка.

## 5. Freelance.ru / Freelancehunt

В Railway Variables:

```
FREELANCE_RU_ENABLED=true
FREELANCE_RU_SEARCH_URL=https://freelance.ru/project/search?q=python
FREELANCEHUNT_ENABLED=true
FREELANCEHUNT_PROJECTS_URL=https://freelancehunt.com/projects/skill/veb-programmirovanie/99.html
```

Логины не обязательны для публичной ленты. Первый прогон — baseline (старые не шлём).

## 6. Если в логах ошибка

| Лог | Действие |
|-----|----------|
| `Kwork auth failed` | проверить логин/пароль; иногда нужен email, не ник |
| `Kwork poll failed` | подождать / смотреть текст error |
| `FL.ru poll failed` | часто капча/вёрстка; мониторинг публичной ленты может работать и без логина |
| `Freelance.ru poll failed` / `Freelancehunt poll failed` | вёрстка/блок; проверить URL ленты |
| `Daily draft limit` | лимит на день; завтра или поднять `max_drafts_per_day` в `config/profile.yaml` |

## 7. Проверка

В боте: «Очередь» — ждут показа N; активная одна.  
`/stats` — растут `seen` / `matched` / `notified` с источниками `fl_ru`, `kwork`, `freelance_ru`, `freelancehunt`.