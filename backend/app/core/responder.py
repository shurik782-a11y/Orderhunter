import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from openai import APIStatusError, AsyncOpenAI, AuthenticationError

from app.config import get_settings
from app.core.dedup import load_portfolio
from app.core.matcher import MatchResult, parse_budget_bounds
from app.core.normalizer import NormalizedOrder

logger = logging.getLogger(__name__)

_llm_disabled_reason: str | None = None


@dataclass
class DraftBundle:
    score: float
    case_slug: str
    draft: str
    client_need: str
    my_offer: str
    price_rub: int
    price_note: str
    intent_title: str
    title_ru: str = ""
    fit: bool = True
    risk_flags: list[str] = field(default_factory=list)


def _resolve_llm_client(settings) -> tuple[AsyncOpenAI, str]:
    api_key = (settings.llm_api_key or "").strip()
    base_url = (settings.llm_base_url or "").strip().rstrip("/")
    model = (settings.llm_model or "").strip()

    if api_key.startswith("sk-or-") or "openrouter.ai" in base_url:
        if "openrouter.ai" not in base_url:
            base_url = "https://openrouter.ai/api/v1"
        if not model or model == "deepseek-chat":
            model = "deepseek/deepseek-chat"
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/shurik782-a11y/Orderhunter",
                "X-Title": "OrderHunter",
            },
        )
        return client, model

    if not base_url:
        base_url = "https://api.deepseek.com"
    if not model:
        model = "deepseek-chat"
    return AsyncOpenAI(api_key=api_key, base_url=base_url), model


def _clamp_price(
    price: int,
    floor: int,
    budget_max: int | None,
) -> tuple[int, str]:
    """Keep price >= niche floor when possible, but never above client ceiling."""
    note = ""
    p = max(int(price or floor or 0), 0)
    if floor and p < floor and (budget_max is None or budget_max >= floor):
        p = floor
    if budget_max is not None and budget_max > 0:
        if p > budget_max:
            p = budget_max
            note = f"у потолка заказчика ({budget_max} ₽)"
        if floor and budget_max < floor:
            # Still offer at ceiling; note mismatch
            note = note or f"бюджет заказчика {budget_max} ₽ ниже обычного floor"
    return max(p, 500), note


def _extract_conditions(description: str, limit: int = 5) -> list[str]:
    """Pull concrete requirement-like lines for template drafts."""
    lines: list[str] = []
    for raw in (description or "").splitlines():
        ln = raw.strip(" •-\t")
        if len(ln) < 12 or len(ln) > 180:
            continue
        low = ln.lower()
        if any(
            k in low
            for k in (
                "нужн",
                "надо",
                "требуется",
                "важно",
                "обязательн",
                "срок",
                "бюджет",
                "адаптив",
                "анимац",
                "верстк",
                "интеграц",
                "api",
                "бот",
                "лендинг",
                "bem",
                "pixel",
                "мобильн",
            )
        ):
            lines.append(ln)
        if len(lines) >= limit:
            break
    if not lines:
        # fallback: first meaningful sentences
        parts = re.split(r"[.!?]\s+", (description or "").strip())
        for p in parts:
            p = p.strip()
            if 20 <= len(p) <= 160:
                lines.append(p)
            if len(lines) >= 2:
                break
    return lines[:limit]


class DraftGenerator:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.settings = get_settings()
        profile_path = config_dir / "profile.yaml"
        with profile_path.open(encoding="utf-8") as f:
            self.profile = yaml.safe_load(f)

    async def classify_and_draft(
        self,
        order: NormalizedOrder,
        match: MatchResult,
    ) -> DraftBundle:
        global _llm_disabled_reason

        if (
            not self.settings.llm_enabled
            or not self.settings.llm_api_key
            or _llm_disabled_reason
        ):
            return self._template_bundle(order, match)

        client, model = _resolve_llm_client(self.settings)
        portfolio = load_portfolio(self.config_dir)
        case = next((c for c in portfolio if c["slug"] == match.case_slug), None)
        pricing = self.profile.get("pricing", {})
        snippets = self.profile.get("offer_snippets", {})
        can_do = self.profile.get("developer", {}).get("can_do", "")

        _, budget_max = parse_budget_bounds(
            f"{order.budget_text} {order.description} {order.title}".strip()
        )
        if match.budget_max_rub:
            budget_max = match.budget_max_rub
        elif order.budget_min_rub and budget_max is None:
            # Kwork: stored figure is usually priceLimit (ceiling)
            if order.source == "kwork":
                budget_max = order.budget_min_rub

        system = """Ты ассистент фрилансера (Assist). Сначала ВНИМАТЕЛЬНО изучи ТЗ, потом реши fit.
Верни ТОЛЬКО JSON:
{
  "score": 0-100,
  "fit": true/false,
  "title_ru": "краткий заголовок заказа на русском (1 строка)",
  "client_need": "1-2 предложения: чего хочет заказчик — по факту из ТЗ, не общие слова",
  "my_offer": "1-2 предложения: что конкретно сделаю под ЭТО ТЗ",
  "price_rub": целое — цена для отклика,
  "price_note": "кратко почему такая цена",
  "suggested_case_slug": "slug из портфолио или пусто",
  "draft": "готовый текст отклика ТОЛЬКО на русском 130-260 слов",
  "risk_flags": ["краткие флаги риска или пусто"],
  "conditions_used": ["2-5 конкретных условий из ТЗ, которые учёл в отклике"]
}
Правила отбора (fit=false, score<=40, draft=""):
- Не IT-заказ / вакансия / HR / Авито / «только для парней» / визы / MLM / накрутки / эскорт / гадания.
- Бредовая или серая схема, нет реальной задачи разработки.
- Заказ вне ниш: сайт/веб, бот/Mini App, автоматизация, интеграция/API, починить, парсер.
- Бюджет заказчика (budget_max_rub) сильно ниже price_min_rub и объём явно большой — fit=false.
Правила отклика (fit=true):
- ВЕСЬ текст JSON — только русский (украинский/английский ТЗ → переведи смысл).
- Индивидуально: в draft явно отрази 2+ условия из ТЗ (стек, анимации, адаптив, интеграции, сроки и т.п.).
- Не пиши шаблон «сделаю качественно»; покажи, что прочитал бриф.
- Не выдумывай кейсы и цифры вне pricing/portfolio.
- price_rub >= price_min_rub, НО если задан budget_max_rub > 0 — price_rub НЕ выше budget_max_rub.
- draft структура:
  1) понял задачу + 1-2 детали из ТЗ
  2) как сделаю / стек под их условия
  3) релевантный кейс если есть
  4) цена (в рамках потолка) и сроки
  5) 1 уточняющий вопрос по главному риску ТЗ + CTA
- Тон: деловой, без эмодзи, без воды."""

        user = json.dumps(
            {
                "order": {
                    "title": order.title,
                    "description": order.description[:6000],
                    "source": order.source,
                    "budget_text": order.budget_text,
                    "budget_max_rub": budget_max,
                },
                "match": {
                    "rules_score": match.score,
                    "reasons": match.reasons,
                    "intent": match.intent_id,
                    "intent_title": match.intent_title,
                    "price_min_rub": match.price_min_rub,
                    "client_need_hint": match.client_need,
                },
                "developer": self.profile.get("developer", {}),
                "can_do": can_do,
                "pricing": pricing,
                "suggested_case": case,
                "snippets": snippets,
                "portfolio_slugs": [c.get("slug") for c in portfolio],
            },
            ensure_ascii=False,
        )

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.25,
                response_format={"type": "json_object"},
            )
        except AuthenticationError as e:
            _llm_disabled_reason = str(e)
            logger.error("LLM auth failed — templates. %s", e)
            return self._template_bundle(order, match)
        except APIStatusError as e:
            logger.warning("LLM API %s — template", e.status_code)
            return self._template_bundle(order, match)

        raw = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._template_bundle(order, match)

        fit = bool(data.get("fit", True))
        score = float(data.get("score", match.score))
        risk_flags = [str(x) for x in (data.get("risk_flags") or [])][:8]
        if not fit:
            score = min(score, 40.0)
            return DraftBundle(
                score=score,
                case_slug="",
                draft="",
                client_need=str(data.get("client_need") or match.client_need)[:400],
                my_offer="",
                price_rub=match.price_min_rub or 0,
                price_note="отклонено LLM",
                intent_title=match.intent_title or "Проект",
                title_ru=str(data.get("title_ru") or order.title)[:200],
                fit=False,
                risk_flags=risk_flags or ["llm_reject"],
            )

        price = int(data.get("price_rub") or match.price_min_rub or 25000)
        price, clamp_note = _clamp_price(price, match.price_min_rub or 0, budget_max)
        price_note = str(data.get("price_note") or "ориентир до брифа")[:200]
        if clamp_note:
            price_note = f"{price_note}; {clamp_note}"[:200]

        draft = str(data.get("draft", "")).strip()
        slug = str(data.get("suggested_case_slug") or match.case_slug or "")
        if not draft and score >= 50:
            return self._template_bundle(order, match)

        return DraftBundle(
            score=score,
            case_slug=slug,
            draft=draft or self._template_bundle(order, match).draft,
            client_need=str(data.get("client_need") or match.client_need)[:400],
            my_offer=str(data.get("my_offer") or "")[:400]
            or self._default_offer(match),
            price_rub=price,
            price_note=price_note,
            intent_title=match.intent_title or "Проект",
            title_ru=str(data.get("title_ru") or order.title)[:200],
            fit=True,
            risk_flags=risk_flags,
        )

    def _default_offer(self, match: MatchResult) -> str:
        mapping = {
            "site": "Соберу сайт/веб на Next.js или доработаю существующий стек, деплой и базовая админка.",
            "bot": "Сделаю Telegram-бота / Mini App под ключ: сценарии, БД, оплаты/уведомления при необходимости.",
            "automation": "Автоматизирую процесс: скрипты/воркер, расписание, интеграции, мониторинг ошибок.",
            "integration": "Свяжу сервисы через API/webhook, обработаю ошибки и логирование.",
            "fix": "Найду причину, починю на prod, дам короткий отчёт что было и как не повторится.",
            "parse": "Напишу парсер/сбор данных с антибаном по необходимости, выгрузку и расписание.",
        }
        return mapping.get(
            match.intent_id,
            "Сделаю разработку под задачу: анализ → реализация → деплой.",
        )

    def _template_bundle(self, order: NormalizedOrder, match: MatchResult) -> DraftBundle:
        _, budget_max = parse_budget_bounds(
            f"{order.budget_text} {order.description}".strip()
        )
        if match.budget_max_rub:
            budget_max = match.budget_max_rub
        elif order.source == "kwork" and order.budget_min_rub:
            budget_max = order.budget_min_rub
        price, clamp_note = _clamp_price(
            match.price_min_rub
            or int(self.profile.get("pricing", {}).get("project_min_rub", 25000)),
            match.price_min_rub or 0,
            budget_max,
        )
        note = "минимум по нише; точнее после брифа"
        if clamp_note:
            note = clamp_note
        return DraftBundle(
            score=match.score,
            case_slug=match.case_slug,
            draft=self._template_draft(order, match, price),
            client_need=match.client_need or order.title[:200],
            my_offer=self._default_offer(match),
            price_rub=price,
            price_note=note,
            intent_title=match.intent_title or "Проект",
            title_ru=order.title[:200],
            fit=True,
        )

    def _template_draft(
        self, order: NormalizedOrder, match: MatchResult, price: int | None = None
    ) -> str:
        dev = self.profile.get("developer", {})
        snippets = self.profile.get("offer_snippets", {})
        portfolio = load_portfolio(self.config_dir)
        case = next((c for c in portfolio if c["slug"] == match.case_slug), None)
        case_line = ""
        if case:
            case_line = (
                f"Похожий опыт: {case['title']} — "
                f"{case['results'][0] if case.get('results') else case.get('subtitle', '')}."
            )
        price = price or match.price_min_rub or 25000
        need = match.client_need or order.title
        offer = self._default_offer(match)
        conditions = _extract_conditions(order.description)
        cond_block = ""
        if conditions:
            bullets = "\n".join(f"— {c}" for c in conditions[:4])
            cond_block = f"\nУчту из ТЗ:\n{bullets}\n"
        return f"""Здравствуйте!

Понял задачу: {need}
{cond_block}
{offer}
{case_line}

Стек: Python/FastAPI, Next.js/React, Telegram-боты, интеграции и парсеры. Работаю удалённо, от ТЗ до деплоя.

Ориентир по бюджету для отклика: {price:,} ₽ (фикс после короткого брифа). Оплата: {self.profile.get('pricing', {}).get('payment', '50/50')}.

Уточните, пожалуйста: какой приоритет по срокам и есть ли референсы/ограничения по стеку?
{snippets.get('cta', '')}

{dev.get('telegram', '@Gersaven')}
""".replace(",", " ")
