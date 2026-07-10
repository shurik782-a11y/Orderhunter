import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramConflictError

from app.bot.handlers import build_dispatcher
from app.bot.leader import release_bot_lock, try_acquire_bot_lock
from app.config import get_settings

logger = logging.getLogger(__name__)

_LOCK_RETRY_SEC = 15
_CONFLICT_RETRY_SEC = 45
_CRASH_RETRY_SEC = 10

# Observed by /health — helps diagnose silent bot after deploy.
bot_runtime: dict[str, str | bool] = {
    "polling": False,
    "state": "starting",
}


async def run_bot() -> None:
    """
    Poll Telegram as a single leader (Postgres advisory lock).

    Important: if the lock is busy (redeploy race / second replica), keep
    retrying — do NOT sleep forever, or the bot stays silent after deploy.
    """
    settings = get_settings()
    if not settings.bot_token:
        logger.warning("BOT_TOKEN not set, bot disabled")
        return

    while True:
        lock_conn = None
        try:
            lock_conn = await try_acquire_bot_lock()
            if lock_conn is None:
                bot_runtime["polling"] = False
                bot_runtime["state"] = "waiting_lock"
                logger.warning(
                    "Bot lock busy — retry in %ss (Replicas=1; stop local bot)",
                    _LOCK_RETRY_SEC,
                )
                await asyncio.sleep(_LOCK_RETRY_SEC)
                continue

            bot = Bot(token=settings.bot_token)
            dp = build_dispatcher()
            bot_runtime["polling"] = True
            bot_runtime["state"] = "polling"
            logger.info("OrderHunter bot polling started (leader)")
            try:
                await dp.start_polling(bot, drop_pending_updates=True)
            finally:
                bot_runtime["polling"] = False
                bot_runtime["state"] = "stopped"
                await bot.session.close()
        except TelegramConflictError:
            bot_runtime["polling"] = False
            bot_runtime["state"] = "conflict"
            logger.error(
                "TelegramConflictError: another getUpdates with the same BOT_TOKEN. "
                "Keep Replicas=1 for orderhunter-api; stop local bot. Retry in %ss",
                _CONFLICT_RETRY_SEC,
            )
            await asyncio.sleep(_CONFLICT_RETRY_SEC)
        except asyncio.CancelledError:
            bot_runtime["polling"] = False
            bot_runtime["state"] = "cancelled"
            raise
        except Exception:
            bot_runtime["polling"] = False
            bot_runtime["state"] = "crashed"
            logger.exception(
                "Bot polling crashed — restart in %ss", _CRASH_RETRY_SEC
            )
            await asyncio.sleep(_CRASH_RETRY_SEC)
        finally:
            await release_bot_lock(lock_conn)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
