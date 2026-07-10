import asyncio
import logging

from aiogram import Bot

from app.bot.handlers import build_dispatcher
from app.config import get_settings

logger = logging.getLogger(__name__)


async def run_bot() -> None:
    settings = get_settings()
    if not settings.bot_token:
        logger.warning("BOT_TOKEN not set, bot disabled")
        return
    bot = Bot(token=settings.bot_token)
    dp = build_dispatcher()
    logger.info("OrderHunter bot polling started")
    await dp.start_polling(bot)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
