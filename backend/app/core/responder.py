import json
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from openai import APIStatusError, AsyncOpenAI, AuthenticationError

from app.config import get_settings
from app.core.dedup import load_portfolio
from app.core.matcher import MatchResult
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

        system = """Ты ассистент фрилансера (Assist). Верни ТОЛЬКО JSON:
{
  "score": 0-100,
  "fit": true/false,
  "client_need": "1-2 предложения: чего хочет заказчик",
  "my_offer": "1-2 предложения: что конкретно сделаю я под его задачу",
  "price_rub": число — ориентир цены для отклика (целое),
  "price_note": "кратко почему такая цена / что входит",
  "suggested_case_slug": "slug из портфолио или пусто",
  "draft": "готовый текст отклика на русском 120-280 слов",
  "risk_flags": []
}
Правила:
- Берём только задачи: сайт/веб, бот, автоматизация, интеграция, починить, парсер.
- Не выдумывай кейсы и цифры вне pricing/portfolio.
- price_rub не ниже price_min_rub из контекста (можно выше, если объём большой).
- draft: без воды; структура:
  1) понял задачу (1 фраза)
  2) как сделаю / стек
  3) релевантный кейс если есть
  4) ориентир цены и сроки
  5) 1 уточняющий вопрос + CTA
- Если не подходит — fit=false, score<50, draft короткий отказ не нужен (пустая строка ок).
- Тон: деловой, уверенный, без эмодзи."""

        user = json.dumps(
            {
                "order": {
                    "title": order.title,
                    "description": order.description[:4500],
                    "source": order.source,
                    "budget_text": order.budget_text,
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
                temperature=0.35,
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

        fit = data.get("fit", True)
        score = float(data.get("score", match.score))
        if fit is False:
            score = min(score, 45.0)

        price = int(data.get("price_rub") or match.price_min_rub or 25000)
        price = max(price, match.price_min_rub or 0)

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
            price_note=str(data.get("price_note") or "ориентир до брифа")[:200],
            intent_title=match.intent_title or "Проект",
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
        return DraftBundle(
            score=match.score,
            case_slug=match.case_slug,
            draft=self._template_draft(order, match),
            client_need=match.client_need or order.title[:200],
            my_offer=self._default_offer(match),
            price_rub=match.price_min_rub or int(
                self.profile.get("pricing", {}).get("project_min_rub", 25000)
            ),
            price_note="минимум по нише; точнее после брифа",
            intent_title=match.intent_title or "Проект",
        )

    def _template_draft(self, order: NormalizedOrder, match: MatchResult) -> str:
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
        price = match.price_min_rub or 25000
        need = match.client_need or order.title
        offer = self._default_offer(match)
        return f"""Здравствуйте!

Понял задачу: {need}

{offer}
{case_line}

Стек: Python/FastAPI, Next.js/React, Telegram-боты, интеграции и парсеры. Работаю удалённо, от ТЗ до деплоя.

Ориентир по бюджету для отклика: от {price:,} ₽ (фикс после короткого брифа). Оплата: {self.profile.get('pricing', {}).get('payment', '50/50')}.

Уточните, пожалуйста: есть ли готовое ТЗ/референсы и желаемые сроки?
{snippets.get('cta', '')}

{dev.get('telegram', '@Gersaven')}
""".replace(",", " ")
