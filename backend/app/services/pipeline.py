import json
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dedup import is_duplicate, order_content_hash
from app.core.matcher import MatchResult, RulesMatcher, parse_budget_rub
from app.core.normalizer import NormalizedOrder
from app.core.profile_loader import get_config_dir, load_profile
from app.core.responder import DraftBundle, DraftGenerator
from app.db.models import Draft, Order, OrderAction, OrderStatus
from app.services.analytics import bump_daily
from app.services.monitor_state import monitor

logger = logging.getLogger(__name__)


class OrderPipeline:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.profile = load_profile()
        self.matcher = RulesMatcher(self.profile)
        self.config_dir = get_config_dir()
        self.drafter = DraftGenerator(self.config_dir)

    async def ingest(self, order: NormalizedOrder) -> Order | None:
        if await is_duplicate(self.session, order):
            return None

        monitor.mark_ingest(order.source, order.title)

        if order.budget_min_rub is None:
            order.budget_min_rub = parse_budget_rub(
                f"{order.budget_text} {order.description}"
            )

        match = self.matcher.match(order)
        min_rules = float(self.profile.thresholds.get("min_score_rules", 28))
        await bump_daily(self.session, "seen")

        if match.score < min_rules:
            return await self._save_order(
                order, match, OrderStatus.IGNORED, brief=None
            )

        await bump_daily(self.session, "matched")

        min_notify = float(self.profile.thresholds.get("min_score_notify", 55))
        min_llm = float(self.profile.thresholds.get("min_score_llm", 50))

        bundle: DraftBundle | None = None
        rules_score = match.score
        score = rules_score

        if rules_score >= min_llm:
            try:
                bundle = await self.drafter.classify_and_draft(order, match)
                score = bundle.score
            except Exception:
                logger.exception("LLM draft failed, using template")
                bundle = self.drafter._template_bundle(order, match)
                score = bundle.score

        # LLM не должен «убивать» сильный rules-матч (fit=false → score≤45)
        if rules_score >= min_notify and score < min_notify:
            logger.info(
                "LLM score %.0f < notify, keeping rules %.0f for %s",
                score,
                rules_score,
                order.title[:80],
            )
            score = rules_score
            if bundle is None:
                bundle = self.drafter._template_bundle(order, match)
            else:
                bundle.score = rules_score

        if score < min_llm and rules_score < min_llm:
            return await self._save_order(
                order, match, OrderStatus.IGNORED, brief=bundle, score=score
            )

        if score < min_notify:
            return await self._save_order(
                order, match, OrderStatus.MATCHED, brief=bundle, score=score
            )

        if not await self._under_daily_draft_limit():
            logger.info("Daily draft limit reached")
            return await self._save_order(
                order, match, OrderStatus.MATCHED, brief=bundle, score=score
            )

        if bundle is None:
            bundle = self.drafter._template_bundle(order, match)

        # Queue as DRAFTED even while paused — cards stay silent until resume.
        row = await self._save_order(
            order, match, OrderStatus.DRAFTED, brief=bundle, score=score
        )
        self.session.add(
            Draft(order_id=row.id, text=bundle.draft, llm_score=score)
        )
        await self.session.commit()
        await self.session.refresh(row)

        from app.services.queue import dispatch_next

        await dispatch_next(self.session)
        return row

    async def _save_order(
        self,
        order: NormalizedOrder,
        match: MatchResult,
        status: OrderStatus,
        brief: DraftBundle | None,
        score: float | None = None,
    ) -> Order:
        meta = {
            "reasons": match.reasons,
            "intent": match.intent_id,
            "intent_title": match.intent_title or (brief.intent_title if brief else ""),
            "client_need": (brief.client_need if brief else match.client_need),
            "my_offer": brief.my_offer if brief else "",
            "price_rub": brief.price_rub if brief else match.price_min_rub,
            "price_note": brief.price_note if brief else "",
        }
        row = Order(
            external_id=order.external_id,
            source=order.source,
            title=order.title,
            description=order.description,
            url=order.url,
            budget_text=order.budget_text,
            budget_min_rub=order.budget_min_rub,
            content_hash=order_content_hash(order),
            match_score=score if score is not None else match.score,
            match_reasons=json.dumps(meta, ensure_ascii=False),
            suggested_case_slug=(
                brief.case_slug if brief and brief.case_slug else match.case_slug
            ),
            status=status,
            posted_at=order.posted_at,
            raw_json=json.dumps(order.raw or {}, ensure_ascii=False),
            contact_hint=order.contact_hint,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _under_daily_draft_limit(self) -> bool:
        max_drafts = int(self.profile.thresholds.get("max_drafts_per_day", 25))
        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        count = await self.session.scalar(
            select(func.count(Order.id)).where(
                Order.status.in_(
                    [
                        OrderStatus.DRAFTED,
                        OrderStatus.NOTIFIED,
                        OrderStatus.APPROVED,
                        OrderStatus.SENT,
                    ]
                ),
                Order.created_at >= day_start,
            )
        )
        return (count or 0) < max_drafts

    async def log_action(self, order_id: int, action: str, meta: dict | None = None) -> None:
        self.session.add(
            OrderAction(
                order_id=order_id,
                action=action,
                meta_json=json.dumps(meta or {}, ensure_ascii=False),
            )
        )
        await bump_daily(self.session, action)
        await self.session.commit()
