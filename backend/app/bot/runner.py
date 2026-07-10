import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramConflictError

from app.bot.handlers import build_dispatcher
from app.bot.leader import release_bot_lock, try_acquire_bot_lock
from app.config import get_settings

logger = logging.getLogger(__name__)


async def run_bot() -> None:
    settings = get_settings()
    if not settings.bot_token:
        logger.warning("BOT_TOKEN not set, bot disabled")
        return

    lock_conn = await try_acquire_bot_lock()
    if lock_conn is None:
        # Stay alive without polling so health/worker keep running on this replica.
        while True:
            await asyncio.sleep(3600)
        return

    bot = Bot(token=settings.bot_token)
    dp = build_dispatcher()
    logger.info("OrderHunter bot polling started (leader)")
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    except TelegramConflictError:
        logger.error(
            "TelegramConflictError: another getUpdates with the same BOT_TOKEN. "
            "Keep Replicas=1 for orderhunter-api; stop local bot."
        )
        raise
    finally:
        await release_bot_lock(lock_conn)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
