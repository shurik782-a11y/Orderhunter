"""Ensure only one process runs aiogram polling (Postgres advisory lock)."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.session import engine

logger = logging.getLogger(__name__)

# Stable 64-bit key for pg_try_advisory_lock
_BOT_LOCK_KEY = 87423001


async def try_acquire_bot_lock() -> AsyncConnection | None:
    """
    Hold an exclusive connection with advisory lock for the bot lifetime.
    Returns the open connection if we are the leader, else None.
    Caller must keep the connection open until polling stops.
    """
    conn = await engine.connect()
    try:
        got = (
            await conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _BOT_LOCK_KEY}
            )
        ).scalar()
        if not got:
            await conn.close()
            logger.warning(
                "Bot lock busy — another replica already polls. "
                "Set orderhunter-api Replicas=1 to avoid duplicate replies."
            )
            return None
        logger.info("Bot leader lock acquired")
        return conn
    except Exception:
        await conn.close()
        raise


async def release_bot_lock(conn: AsyncConnection | None) -> None:
    if conn is None:
        return
    try:
        await conn.execute(
            text("SELECT pg_advisory_unlock(:k)"), {"k": _BOT_LOCK_KEY}
        )
    except Exception:
        logger.exception("Bot lock unlock failed")
    finally:
        await conn.close()
