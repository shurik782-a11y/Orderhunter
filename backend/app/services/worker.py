import asyncio
import logging

from sqlalchemy import select

from app.bot.handlers import notify_order_card
from app.config import get_settings
from app.connectors.fl_ru import FlRuConnector
from app.connectors.kwork import KworkConnector
from app.db.models import Draft, OrderStatus
from app.db.session import async_session
from app.services.pipeline import OrderPipeline

logger = logging.getLogger(__name__)


async def _poll_connector(connector) -> None:
    orders = await connector.poll()
    if not orders:
        return
    async with async_session() as session:
        pipeline = OrderPipeline(session)
        for order in orders:
            row = await pipeline.ingest(order)
            if row and row.status == OrderStatus.DRAFTED:
                draft = await (
                    session.execute(
                        select(Draft)
                        .where(Draft.order_id == row.id)
                        .order_by(Draft.id.desc())
                    )
                ).scalar_one_or_none()
                await session.commit()
                if draft:
                    await notify_order_card(row, draft.text)
            else:
                await session.commit()


async def run_worker_loop() -> None:
    settings = get_settings()
    fl = FlRuConnector()
    kw = KworkConnector()
    fl_interval = settings.fl_ru_poll_interval_seconds
    kw_interval = settings.kwork_poll_interval_seconds
    fl_counter = fl_interval
    kw_counter = kw_interval

    logger.info("Worker loop running")
    while True:
        try:
            if settings.fl_ru_enabled and fl_counter >= fl_interval:
                await _poll_connector(fl)
                fl_counter = 0
            if settings.kwork_enabled and kw_counter >= kw_interval:
                await _poll_connector(kw)
                kw_counter = 0
        except Exception:
            logger.exception("Worker tick error")
        fl_counter += 30
        kw_counter += 30
        await asyncio.sleep(30)
