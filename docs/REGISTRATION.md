# Регистрация на площадках (Этап 0)

Чеклист перед запуском OrderHunter. Выполните вручную — бот не может зарегистрировать аккаунты за вас.

## 1. FL.ru

1. Зарегистрируйтесь: https://www.fl.ru/registration/
2. Заполните профиль исполнителя: fullstack, веб, боты, Python, PHP
3. Добавьте в портфолио: Jummy, BeardNuts, Parfumistery (скриншоты + ссылки)
4. Включите уведомления: Аккаунт → Настройки → Уведомления → раздел «Программирование»
5. Опционально: официальный TG-бот FL.ru (задержка 2–5 мин; OrderHunter быстрее)
6. Сохраните логин/пароль в `.env` как `FL_RU_LOGIN` / `FL_RU_PASSWORD` (для Playwright-сессии)

## 2. Kwork

1. Зарегистрируйтесь: https://kwork.ru/
2. Создайте 3–5 кворков:
   - Telegram-бот под ключ (от 25 000 ₽)
   - Доработка интернет-магазина / e-commerce
   - FastAPI / backend + API
   - Интеграция СДЭК, VK, платежей
3. Подключите «Биржа проектов» (нужны коннекты для откликов)
4. Сохраните в `.env`: `KWORK_LOGIN`, `KWORK_PASSWORD`

## 3. Telegram-каналы

Подпишитесь аккаунтом, для которого создаёте `TELEGRAM_USER_SESSION` (см. `mtproto-worker`).

Список каналов в [`config/telegram-channels.yaml`](../config/telegram-channels.yaml). После подписки отредактируйте файл: уберите `#` у нужных каналов или добавьте свои.

Создание user session:

```bash
cd OrderHunter/mtproto-worker
cp .env.example .env
# TELEGRAM_API_ID, TELEGRAM_API_HASH с https://my.telegram.org
npm install
npm run telegram:login
# скопируйте TELEGRAM_USER_SESSION в .env
```

## 4. Freelancehunt

https://freelancehunt.com/ — профиль + портфолио, категория Python / Web.

## 5. Weblancer

1. https://www.weblancer.net/ — регистрация исполнителя
2. Категория веб-программирования: https://www.weblancer.net/freelance/veb-programmirovanie-31/
3. В Railway: `WEBLANCER_ENABLED=true` (Assist: открыть URL + вставить черновик)

## 6. HabLance (наследник Хабр Фриланс)

1. https://hablance.ru/ — профиль
2. Лента заказов: https://hablance.ru/tasks/
3. В Railway: `HABLANCE_ENABLED=true`

## 7. hh.ru (опционально)

1. Резюме fullstack на hh.ru
2. Приложение на https://dev.hh.ru/ для OAuth (если подключаете коннектор hh)

## Проверка готовности

- [ ] FL.ru профиль заполнен, есть портфолио
- [ ] Kwork: минимум 3 кворка, биржа подключена
- [ ] Weblancer / HabLance (по желанию) + флаги в Railway
- [ ] Подписка на 10+ TG-каналов из конфига (в т.ч. новые: `it_zakazy`, `freelancetaverna`, `javascript_jobs`…)
- [ ] `TELEGRAM_USER_SESSION` создан
- [ ] `.env` backend и mtproto-worker заполнены
