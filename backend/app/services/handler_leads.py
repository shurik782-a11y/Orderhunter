import logging

import httpx

from app.config import get_settings
from app.db.models import Order

logger = logging.getLogger(__name__)


async def push_to_handler_lead(order: Order, draft_text: str) -> bool:
    settings = get_settings()
    if not settings.handler_leads_enabled:
        return False

    service_map = {
        "telegram": "bot",
        "fl_ru": "web",
        "kwork": "web",
    }
    payload = {
        "name": f"OrderHunter: {order.source}",
        "contact": order.contact_hint or "@Gersaven",
        "service": service_map.get(order.source, "consulting"),
        "budget": "discuss",
        "timeline": "flexible",
        "description": (
            f"[{order.source}] {order.title}\n{order.url}\n\n"
            f"Score: {order.match_score}\n\n{draft_text[:1500]}"
        )[:2000],
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(settings.handler_leads_url, json=payload)
            resp.raise_for_status()
            return True
    except Exception:
        logger.exception("Handler lead push failed")
        return False
