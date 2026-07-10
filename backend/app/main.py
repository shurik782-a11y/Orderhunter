import asyncio
import logging

from fastapi import FastAPI

from app.api.router import router
from app.config import get_settings
from app.db.models import Base
from app.db.session import engine
from app.services.worker import run_worker_loop

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="OrderHunter", version="0.1.0")
    app.include_router(router)

    @app.on_event("startup")
    async def startup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        settings = get_settings()
        if settings.worker_enabled:
            asyncio.create_task(run_worker_loop())
            logger.info("Background worker started")
        if settings.bot_token:
            from app.bot.runner import run_bot

            asyncio.create_task(run_bot())
            logger.info("Notify bot started")

    return app


app = create_app()
