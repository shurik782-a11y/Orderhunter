import json
import logging
from pathlib import Path

import yaml
from openai import APIStatusError, AsyncOpenAI, AuthenticationError

from app.config import get_settings
from app.core.dedup import load_portfolio
from app.core.normalizer import NormalizedOrder

logger = logging.getLogger(__name__)

# After 401, skip further LLM calls in this process (use templates).
_llm_disabled_reason: str | None = None


def _resolve_llm_client(settings) -> tuple[AsyncOpenAI, str]:
    """Support DeepSeek and OpenRouter from the same settings."""
    api_key = (settings.llm_api_key or "").strip()
    base_url = (settings.llm_base_url or "").strip().rstrip("/")
    model = (settings.llm_model or "").strip()

    # OpenRouter keys start with sk-or-
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

    # DeepSeek / generic OpenAI-compatible
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
        rules_score: float,
        rules_reasons: list[str],
        case_slug: str,
    ) -> tuple[float, str, str]:
        global _llm_disabled_reason

        if (
            not self.settings.llm_enabled
            or not self.settings.llm_api_key
            or _llm_disabled_reason
        ):
            text = self._template_draft(order, case_slug)
            return rules_score, text, case_slug

        client, model = _resolve_llm_client(self.settings)
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

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.4,
                response_format={"type": "json_object"},
            )
        except AuthenticationError as e:
            _llm_disabled_reason = str(e)
            logger.error(
                "LLM auth failed (check LLM_BASE_URL + LLM_API_KEY for OpenRouter). "
                "Falling back to templates for this process. model=%s base=%s",
                model,
                self.settings.llm_base_url,
            )
            return rules_score, self._template_draft(order, case_slug), case_slug
        except APIStatusError as e:
            logger.warning("LLM API error %s: %s — using template", e.status_code, e.message)
            return rules_score, self._template_draft(order, case_slug), case_slug

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
                f"Похожее делал в проекте {case['title']}: "
                f"{case['results'][0] if case.get('results') else case['subtitle']}."
            )
        return f"""Здравствуйте!

{snippets.get('hook', 'Прочитал ТЗ — задача понятна.')} {order.title[:200]}

{case_line}

Мой стек: Python/FastAPI, Next.js, Telegram-боты и e-commerce. {snippets.get('cta', '')}

Ценовой ориентир по таким задачам — от {pricing.get('bot_min_rub', 25000):,} ₽ для бота / от {pricing.get('landing_min_rub', 30000):,} ₽ для лендинга (точнее после брифа).

Контакт: {dev.get('telegram', '@Gersaven')}
""".replace(",", " ")
