import asyncio
import logging

from app.config import get_settings
from app.connectors.fl_ru import FlRuConnector
from app.connectors.freelance_ru import FreelanceRuConnector
from app.connectors.freelancehunt import FreelancehuntConnector
from app.connectors.kwork import KworkConnector
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
            await pipeline.ingest(order)
            await session.commit()


async def run_worker_loop() -> None:
    settings = get_settings()
    specs = [
        (FlRuConnector(), "fl_ru_enabled", "fl_ru_poll_interval_seconds"),
        (KworkConnector(), "kwork_enabled", "kwork_poll_interval_seconds"),
        (
            FreelanceRuConnector(),
            "freelance_ru_enabled",
            "freelance_ru_poll_interval_seconds",
        ),
        (
            FreelancehuntConnector(),
            "freelancehunt_enabled",
            "freelancehunt_poll_interval_seconds",
        ),
    ]
    # Start at interval so first eligible poll runs on first tick.
    counters = {
        connector.name: getattr(settings, interval_attr)
        for connector, _, interval_attr in specs
    }

    logger.info("Worker loop running")
    while True:
        try:
            for connector, enabled_attr, interval_attr in specs:
                if not getattr(settings, enabled_attr):
                    continue
                interval = getattr(settings, interval_attr)
                if counters[connector.name] >= interval:
                    await _poll_connector(connector)
                    counters[connector.name] = 0
        except Exception:
            logger.exception("Worker tick error")
        for connector, _, _ in specs:
            counters[connector.name] = counters.get(connector.name, 0) + 30
        await asyncio.sleep(30)
