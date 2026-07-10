import json
from pathlib import Path

import yaml
from openai import AsyncOpenAI

from app.config import get_settings
from app.core.dedup import load_portfolio
from app.core.normalizer import NormalizedOrder


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
        rules_score: float,
        rules_reasons: list[str],
        case_slug: str,
    ) -> tuple[float, str, str]:
        if not self.settings.llm_enabled or not self.settings.llm_api_key:
            text = self._template_draft(order, case_slug)
            return rules_score, text, case_slug

        client = AsyncOpenAI(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_base_url,
        )
        portfolio = load_portfolio(self.config_dir)
        case = next((c for c in portfolio if c["slug"] == case_slug), None)
        pricing = self.profile.get("pricing", {})
        snippets = self.profile.get("offer_snippets", {})

        system = """Ты помощник фрилансера. Верни ТОЛЬКО валидный JSON без markdown:
{
  "score": 0-100,
  "risk_flags": ["..."],
  "suggested_case_slug": "slug или пусто",
  "draft": "текст отклика 150-400 слов на русском"
}
Правила:
- Не выдумывай цифры и кейсы — только из контекста
- Тон: деловой B2B, без воды
- Структура draft: крючок → релевантный кейс → как сделаешь → 1 вопрос → CTA
- Если заказ не подходит — score < 60"""

        user = json.dumps(
            {
                "order": {
                    "title": order.title,
                    "description": order.description[:4000],
                    "source": order.source,
                    "budget": order.budget_text,
                },
                "developer": self.profile.get("developer", {}),
                "pricing": pricing,
                "rules_score": rules_score,
                "rules_reasons": rules_reasons,
                "suggested_case": case,
                "snippets": snippets,
            },
            ensure_ascii=False,
        )

        resp = await client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        score = float(data.get("score", rules_score))
        draft = str(data.get("draft", "")).strip()
        slug = str(data.get("suggested_case_slug", case_slug)) or case_slug
        if not draft:
            draft = self._template_draft(order, slug)
        return score, draft, slug

    def _template_draft(self, order: NormalizedOrder, case_slug: str) -> str:
        dev = self.profile.get("developer", {})
        pricing = self.profile.get("pricing", {})
        snippets = self.profile.get("offer_snippets", {})
        portfolio = load_portfolio(self.config_dir)
        case = next((c for c in portfolio if c["slug"] == case_slug), None)
        case_line = ""
        if case:
            case_line = (
                f"Похожее делал в проекте {case['title']}: {case['results'][0] if case.get('results') else case['subtitle']}."
            )
        return f"""Здравствуйте!

{snippets.get('hook', 'Прочитал ТЗ — задача понятна.')} {order.title[:200]}

{case_line}

Мой стек: Python/FastAPI, Next.js, Telegram-боты и e-commerce. {snippets.get('cta', '')}

Ценовой ориентир по таким задачам — от {pricing.get('bot_min_rub', 25000):,} ₽ для бота / от {pricing.get('landing_min_rub', 30000):,} ₽ для лендинга (точнее после брифа).

Контакт: {dev.get('telegram', '@Gersaven')}
""".replace(",", " ")
