from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalyticsDaily

_ACTION_MAP = {
    "matched": "matched",
    "notified": "notified",
    "approved": "approved",
    "sent": "sent",
    "skipped": "skipped",
    "client_replied": "client_replied",
}


async def bump_daily(session: AsyncSession, metric: str) -> None:
    day = datetime.now(UTC).date().isoformat()
    row = await session.scalar(select(AnalyticsDaily).where(AnalyticsDaily.day == day))
    if not row:
        row = AnalyticsDaily(day=day)
        session.add(row)
        await session.flush()

    if metric == "seen":
        row.seen += 1
    elif metric in _ACTION_MAP:
        setattr(row, _ACTION_MAP[metric], getattr(row, _ACTION_MAP[metric]) + 1)
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
