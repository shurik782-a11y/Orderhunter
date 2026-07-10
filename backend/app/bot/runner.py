import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramConflictError

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
    try:
        # Drop backlog so a redeploy doesn't fight an old replica forever.
        await dp.start_polling(bot, drop_pending_updates=True)
    except TelegramConflictError:
        logger.error(
            "TelegramConflictError: another getUpdates is running with the same BOT_TOKEN. "
            "Keep only ONE replica of orderhunter-api; stop local python -m app.bot.runner."
        )
        raise


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
