import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.normalizer import NormalizedOrder
from app.core.matcher import content_hash
from app.db.models import Order


async def is_duplicate(session: AsyncSession, order: NormalizedOrder) -> bool:
    h = content_hash(order.title, order.description)
    existing = await session.scalar(
        select(Order.id).where(
            (Order.external_id == order.external_id) | (Order.content_hash == h)
        )
    )
    return existing is not None


def order_content_hash(order: NormalizedOrder) -> str:
    return content_hash(order.title, order.description)


def load_portfolio(config_dir: Path) -> list[dict]:
    path = config_dir / "portfolio.json"
    return json.loads(path.read_text(encoding="utf-8"))
