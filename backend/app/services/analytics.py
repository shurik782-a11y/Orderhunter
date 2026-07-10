from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalyticsDaily, Order, OrderStatus


async def bump_daily(session: AsyncSession, metric: str) -> None:
    day = datetime.now(UTC).date().isoformat()
    row = await session.scalar(select(AnalyticsDaily).where(AnalyticsDaily.day == day))
    if not row:
        row = AnalyticsDaily(
            day=day,
            seen=0,
            matched=0,
            notified=0,
            approved=0,
            sent=0,
            skipped=0,
            client_replied=0,
        )
        session.add(row)
        await session.flush()

    mapping = {
        "seen": "seen",
        "matched": "matched",
        "notified": "notified",
        "approved": "approved",
        "sent": "sent",
        "skipped": "skipped",
        "client_replied": "client_replied",
    }
    if metric == "seen":
        row.seen += 1
    elif metric in mapping:
        setattr(row, mapping[metric], getattr(row, mapping[metric]) + 1)
    await session.flush()


async def get_funnel(session: AsyncSession, days: int = 30) -> list[dict]:
    result = await session.execute(
        select(AnalyticsDaily).order_by(AnalyticsDaily.day.desc()).limit(days)
    )
    rows = result.scalars().all()
    return [
        {
            "day": r.day,
            "seen": r.seen,
            "matched": r.matched,
            "notified": r.notified,
            "approved": r.approved,
            "sent": r.sent,
            "skipped": r.skipped,
            "client_replied": r.client_replied,
        }
        for r in rows
    ]


async def get_dashboard(session: AsyncSession) -> dict:
    """Aggregates for bot status/stats screens."""
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today = day_start.date().isoformat()

    daily = await session.scalar(select(AnalyticsDaily).where(AnalyticsDaily.day == today))

    status_rows = (
        await session.execute(
            select(Order.status, func.count(Order.id)).group_by(Order.status)
        )
    ).all()
    by_status = {str(s.value if hasattr(s, "value") else s): c for s, c in status_rows}

    source_today = (
        await session.execute(
            select(Order.source, func.count(Order.id))
            .where(Order.created_at >= day_start)
            .group_by(Order.source)
        )
    ).all()
    by_source_today = {src: cnt for src, cnt in source_today}

    queue = (
        await session.execute(
            select(Order)
            .where(Order.status.in_([OrderStatus.NOTIFIED, OrderStatus.DRAFTED]))
            .order_by(Order.id.desc())
            .limit(8)
        )
    ).scalars().all()

    pending = await session.scalar(
        select(func.count(Order.id)).where(
            Order.status.in_([OrderStatus.NOTIFIED, OrderStatus.DRAFTED])
        )
    )

    return {
        "today": {
            "seen": daily.seen if daily else 0,
            "matched": daily.matched if daily else 0,
            "notified": daily.notified if daily else 0,
            "sent": daily.sent if daily else 0,
            "skipped": daily.skipped if daily else 0,
        },
        "by_status": by_status,
        "by_source_today": by_source_today,
        "pending": pending or 0,
        "queue": queue,
    }
