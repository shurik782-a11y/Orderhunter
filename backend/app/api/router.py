from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.telegram_bridge import ingest_telegram_payload
from app.db.session import get_db
from app.services.analytics import get_funnel
from app.services.pipeline import OrderPipeline

router = APIRouter()


class TelegramIngestBody(BaseModel):
    message_id: int
    channel: str
    text: str
    url: str = ""
    contact_hint: str = ""


def verify_internal(x_internal_secret: str = Header(default="")) -> None:
    settings = get_settings()
    if x_internal_secret != settings.internal_api_secret:
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/internal/telegram/ingest", dependencies=[Depends(verify_internal)])
async def ingest_telegram(
    body: TelegramIngestBody,
    session: AsyncSession = Depends(get_db),
) -> dict:
    order = ingest_telegram_payload(body.model_dump())
    pipeline = OrderPipeline(session)
    row = await pipeline.ingest(order)
    await session.commit()
    if not row:
        return {"ok": True, "action": "ignored_or_duplicate", "order_id": None}
    return {
        "ok": True,
        "action": row.status.value if hasattr(row.status, "value") else str(row.status),
        "order_id": row.id,
    }


@router.get("/analytics/funnel")
async def analytics_funnel(
    days: int = 30,
    session: AsyncSession = Depends(get_db),
) -> dict:
    return {"funnel": await get_funnel(session, days=days)}


@router.get("/health")
async def health() -> dict:
    from app.bot.runner import bot_runtime
    from app.config import get_settings

    settings = get_settings()
    bot = {
        "configured": bool(settings.bot_token),
        **bot_runtime,
    }
    return {"status": "ok", "service": "orderhunter", "bot": bot}
