from pathlib import Path
import sys

sys.path.insert(0, "backend")

from app.core.matcher import RulesMatcher, parse_budget_bounds, parse_budget_rub
from app.core.normalizer import NormalizedOrder
from app.core.profile_loader import load_profile
from app.core.responder import DraftGenerator, _clamp_price

p = load_profile()
m = RulesMatcher(p)
d = DraftGenerator(Path(p.data["_config_dir"]))

print("bounds", parse_budget_bounds("24000"), parse_budget_bounds("1600-24000"), parse_budget_rub("24000"))
print("clamp", _clamp_price(30000, 30000, 24000))

cases = [
    ("visa", "kwork", "Продажа визовых услуг по телефону и месенджерам", "Нужны операторы, продажа виз, доход от 100", ""),
    ("guys", "telegram", "Робота тільки для хлопців", "Шукаємо співробітників, вакансія, повний день", ""),
    (
        "landing",
        "kwork",
        "Редизайн лендинга арбитраж",
        "Нужен редизайн и верстка лендинга, BEM, анимации, адаптив, быстрая загрузка",
        "24000",
    ),
    ("bot", "kwork", "Telegram bot CRM", "Нужен telegram бот для записи клиентов aiogram", ""),
    ("logo", "kwork", "Только логотип", "Нужен логотип и копирайтинг статьи", ""),
]

for name, source, title, desc, budget in cases:
    o = NormalizedOrder("x", source, title, desc, "", budget_text=budget)
    if budget:
        o.budget_min_rub = int(budget)
    r = m.match(o)
    b = d._template_bundle(o, r)
    print(
        f"{r.score:5.1f} | {name:8} | {(r.intent_id or '-'):12} | "
        f"price={b.price_rub} | {r.reasons[:3]}"
    )
