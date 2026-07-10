from app.core.matcher import RulesMatcher
from app.core.normalizer import NormalizedOrder
from app.core.profile_loader import load_profile
from app.core.responder import DraftGenerator
from app.config import get_settings

get_settings.cache_clear()
p = load_profile()
m = RulesMatcher(p)
d = DraftGenerator(p.data.get("_config_dir") and __import__("pathlib").Path(p.data["_config_dir"]) or __import__("pathlib").Path("../config"))

tests = [
    ("Telegram bot CRM", "Нужен telegram бот для записи клиентов aiogram"),
    ("Сделать лендинг", "Нужен сайт лендинг для услуг next.js"),
    ("Спарсить цены", "Нужен парсер магазинов playwright сбор данных"),
    ("Починить ошибку", "На сайте не работает оплата, починить срочно"),
    ("Интеграция СДЭК", "Подключить СДЭК API к магазину webhook"),
    ("Только логотип", "Нужен логотип и копирайтинг статьи"),
    ("Автоматизация постов", "Автоматизация автопост VK и telegram очередь"),
]

for title, desc in tests:
    o = NormalizedOrder("x", "tg", title, desc, "")
    r = m.match(o)
    b = d._template_bundle(o, r)
    print(
        f"{r.score:5.1f} | {(r.intent_id or '-'):12} | {b.price_rub:6} | "
        f"{title} | need={b.client_need[:40]}"
    )
