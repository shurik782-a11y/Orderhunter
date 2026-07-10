import asyncio
import logging

from fastapi import FastAPI

from app.api.router import router
from app.config import get_settings
from app.db.models import Base
from app.db.session import engine
from app.services.worker import run_worker_loop

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def _init_db_with_retry(attempts: int = 10) -> None:
    for i in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema ready")
            return
        except Exception:
            logger.exception("DB init attempt %s/%s failed", i, attempts)
            if i < attempts:
                await asyncio.sleep(min(2 * i, 15))
    logger.error("Database init failed after retries — API up, worker may fail")


def create_app() -> FastAPI:
    app = FastAPI(title="OrderHunter", version="0.1.0")
    app.include_router(router)

    @app.on_event("startup")
    async def startup() -> None:
        # Do not block readiness forever; health responds even while DB retries.
        asyncio.create_task(_bootstrap())

    return app


def _log_task_done(task: asyncio.Task, name: str) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error("%s task died: %s", name, exc, exc_info=exc)


async def _bootstrap() -> None:
    await _init_db_with_retry()
    settings = get_settings()
    if settings.worker_enabled:
        t = asyncio.create_task(run_worker_loop(), name="worker")
        t.add_done_callback(lambda task: _log_task_done(task, "worker"))
        logger.info("Background worker started")
    if settings.bot_token:
        from app.bot.runner import run_bot

        t = asyncio.create_task(run_bot(), name="bot")
        t.add_done_callback(lambda task: _log_task_done(task, "bot"))
        logger.info("Notify bot started")
    else:
        logger.warning("BOT_TOKEN empty — notify bot disabled")


app = create_app()
