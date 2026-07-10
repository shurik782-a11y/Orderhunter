"""Bridge for orders ingested from mtproto-worker HTTP callbacks."""

from app.core.normalizer import NormalizedOrder, normalize_telegram_post


def ingest_telegram_payload(payload: dict) -> NormalizedOrder:
    return normalize_telegram_post(
        message_id=int(payload["message_id"]),
        channel=str(payload.get("channel", "")),
        text=str(payload.get("text", "")),
        url=str(payload.get("url", "")),
        contact_hint=str(payload.get("contact_hint", "")),
    )
