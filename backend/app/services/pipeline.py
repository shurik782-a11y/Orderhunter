import json
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dedup import is_duplicate, order_content_hash
from app.core.matcher import RulesMatcher, parse_budget_rub
from app.core.normalizer import NormalizedOrder
from app.core.profile_loader import get_config_dir, load_profile
from app.core.responder import DraftGenerator
from app.db.models import Draft, Order, OrderAction, OrderStatus
from app.services.analytics import bump_daily

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

        if order.budget_min_rub is None:
            order.budget_min_rub = parse_budget_rub(
                f"{order.budget_text} {order.description}"
            )

        score, reasons, case_slug = self.matcher.match(order)
        min_rules = float(self.profile.thresholds.get("min_score_rules", 40))
        await bump_daily(self.session, "seen")

        if score < min_rules:
            row = await self._save_order(
                order, score, reasons, case_slug, OrderStatus.IGNORED
            )
            return row

        await bump_daily(self.session, "matched")
        llm_score = score
        draft_text = ""
        final_case = case_slug

        min_notify = float(self.profile.thresholds.get("min_score_notify", 65))
        min_llm = float(self.profile.thresholds.get("min_score_llm", 60))
        if score >= min_llm:
            try:
                llm_score, draft_text, final_case = await self.drafter.classify_and_draft(
                    order, score, reasons, case_slug
                )
            except Exception:
                logger.exception("LLM draft failed, using rules only")
                draft_text = self.drafter._template_draft(order, case_slug)

        if llm_score < min_llm:
            row = await self._save_order(
                order, llm_score, reasons, final_case, OrderStatus.IGNORED
            )
            return row

        # Notify threshold: below notify score — store matched but don't draft-spam
        if llm_score < min_notify:
            row = await self._save_order(
                order, llm_score, reasons, final_case, OrderStatus.MATCHED
            )
            return row

        if not await self._under_daily_draft_limit():
            logger.info("Daily draft limit reached")
            row = await self._save_order(
                order, llm_score, reasons, final_case, OrderStatus.MATCHED
            )
            return row

        row = await self._save_order(
            order, llm_score, reasons, final_case, OrderStatus.DRAFTED
        )
        if draft_text:
            self.session.add(Draft(order_id=row.id, text=draft_text, llm_score=llm_score))
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def _save_order(
        self,
        order: NormalizedOrder,
        score: float,
        reasons: list[str],
        case_slug: str,
        status: OrderStatus,
    ) -> Order:
        row = Order(
            external_id=order.external_id,
            source=order.source,
            title=order.title,
            description=order.description,
            url=order.url,
            budget_text=order.budget_text,
            budget_min_rub=order.budget_min_rub,
            content_hash=order_content_hash(order),
            match_score=score,
            match_reasons=json.dumps(reasons, ensure_ascii=False),
            suggested_case_slug=case_slug,
            status=status,
            posted_at=order.posted_at,
            raw_json=json.dumps(order.raw or {}, ensure_ascii=False),
            contact_hint=order.contact_hint,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _under_daily_draft_limit(self) -> bool:
        max_drafts = int(self.profile.thresholds.get("max_drafts_per_day", 5))
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
