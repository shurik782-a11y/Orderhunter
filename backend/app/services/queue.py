"""Sequential Assist queue: one active NOTIFIED card at a time."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Draft, Order, OrderStatus
from app.db.session import async_session
from app.services.monitor_state import monitor

logger = logging.getLogger(__name__)


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


async def dispatch_next(session: AsyncSession | None = None) -> Order | None:
    """
    If no active NOTIFIED card and not paused — send oldest DRAFTED to chat.
    Returns the order that was notified, or None.
    """
    from app.bot.handlers import notify_order_card

    async def _run(sess: AsyncSession) -> Order | None:
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

        # Detach values before notify (opens its own session / sets NOTIFIED)
        text = draft.text
        order_id = order.id
        await sess.commit()
        await notify_order_card(order, text)
        logger.info("dispatch_next notified order %s", order_id)
        return order

    if session is not None:
        return await _run(session)

    async with async_session() as sess:
        return await _run(sess)
