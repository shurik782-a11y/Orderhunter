"""Sequential Assist queue: one active NOTIFIED card at a time."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Draft, Order, OrderStatus
from app.db.session import async_session
from app.services.monitor_state import monitor

logger = logging.getLogger(__name__)

STALE_NOTIFIED_HOURS = 2


async def has_active_card(session: AsyncSession) -> bool:
    count = await session.scalar(
        select(func.count(Order.id)).where(Order.status == OrderStatus.NOTIFIED)
    )
    return (count or 0) > 0


async def queued_count(session: AsyncSession) -> int:
    """DRAFTED waiting to be shown (not yet in chat)."""
    count = await session.scalar(
        select(func.count(Order.id)).where(Order.status == OrderStatus.DRAFTED)
    )
    return count or 0


async def peek_next_drafted(session: AsyncSession) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.status == OrderStatus.DRAFTED)
        .order_by(Order.id.asc())
        .limit(1)
    )


async def list_queued(session: AsyncSession, limit: int = 12) -> list[Order]:
    rows = await session.scalars(
        select(Order)
        .where(Order.status == OrderStatus.DRAFTED)
        .order_by(Order.id.asc())
        .limit(limit)
    )
    return list(rows)


async def get_active_card(session: AsyncSession) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.status == OrderStatus.NOTIFIED)
        .order_by(Order.id.desc())
        .limit(1)
    )


async def release_stale_notified(
    session: AsyncSession, hours: float = STALE_NOTIFIED_HOURS
) -> int:
    """Mark old NOTIFIED as SKIPPED so the queue can move."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    result = await session.execute(
        update(Order)
        .where(
            Order.status == OrderStatus.NOTIFIED,
            Order.updated_at < cutoff,
        )
        .values(status=OrderStatus.SKIPPED)
    )
    await session.commit()
    n = result.rowcount or 0
    if n:
        logger.info("Released %s stale NOTIFIED (>%sh) → SKIPPED", n, hours)
    return n


async def skip_active(session: AsyncSession) -> Order | None:
    """Skip current NOTIFIED card (all of them) so next can show."""
    actives = (
        await session.scalars(
            select(Order).where(Order.status == OrderStatus.NOTIFIED)
        )
    ).all()
    if not actives:
        return None
    last = actives[0]
    for o in actives:
        o.status = OrderStatus.SKIPPED
    await session.commit()
    return last


async def dispatch_next(session: AsyncSession | None = None) -> Order | None:
    """
    If no active NOTIFIED card and not paused — send oldest DRAFTED to chat.
    Returns the order that was notified, or None.
    """
    from app.bot.handlers import notify_order_card

    async def _run(sess: AsyncSession) -> Order | None:
        await release_stale_notified(sess)
        if monitor.paused:
            logger.info("dispatch_next skipped: paused")
            return None
        if await has_active_card(sess):
            logger.debug("dispatch_next skipped: active card exists")
            return None

        order = await peek_next_drafted(sess)
        if not order:
            return None

        draft = await sess.scalar(
            select(Draft).where(Draft.order_id == order.id).order_by(Draft.id.desc())
        )
        if not draft:
            logger.warning(
                "DRAFTED order %s has no draft — marking MATCHED", order.id
            )
            order.status = OrderStatus.MATCHED
            await sess.commit()
            return await _run(sess)

        text = draft.text
        order_id = order.id
        await sess.commit()
        ok = await notify_order_card(order, text)
        if not ok:
            logger.warning("dispatch_next: notify failed for order %s", order_id)
            return None
        logger.info("dispatch_next notified order %s", order_id)
        return order

    if session is not None:
        return await _run(session)

    async with async_session() as sess:
        return await _run(sess)
