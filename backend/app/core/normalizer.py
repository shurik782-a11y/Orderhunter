from dataclasses import dataclass
from datetime import datetime


@dataclass
class NormalizedOrder:
    external_id: str
    source: str
    title: str
    description: str
    url: str
    budget_text: str = ""
    budget_min_rub: int | None = None
    posted_at: datetime | None = None
    contact_hint: str = ""
    raw: dict | None = None


def normalize_telegram_post(
    message_id: int,
    channel: str,
    text: str,
    url: str = "",
    contact_hint: str = "",
) -> NormalizedOrder:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = lines[0][:500] if lines else text[:500]
    return NormalizedOrder(
        external_id=f"tg:{channel}:{message_id}",
        source="telegram",
        title=title,
        description=text,
        url=url or f"https://t.me/{channel.lstrip('@')}/{message_id}",
        contact_hint=contact_hint,
        raw={"channel": channel, "message_id": message_id},
    )


def normalize_fl_project(
    project_id: str,
    title: str,
    description: str,
    url: str,
    budget_text: str = "",
) -> NormalizedOrder:
    return NormalizedOrder(
        external_id=f"fl:{project_id}",
        source="fl_ru",
        title=title,
        description=description,
        url=url,
        budget_text=budget_text,
        raw={"project_id": project_id},
    )


def normalize_kwork_project(
    project_id: int,
    title: str,
    description: str,
    url: str,
    budget_text: str = "",
) -> NormalizedOrder:
    return NormalizedOrder(
        external_id=f"kwork:{project_id}",
        source="kwork",
        title=title,
        description=description,
        url=url,
        budget_text=budget_text,
        raw={"project_id": project_id},
    )


def normalize_freelance_ru_task(
    task_id: str,
    title: str,
    description: str,
    url: str,
    budget_text: str = "",
) -> NormalizedOrder:
    return NormalizedOrder(
        external_id=f"freelance_ru:{task_id}",
        source="freelance_ru",
        title=title,
        description=description,
        url=url,
        budget_text=budget_text,
        raw={"task_id": task_id},
    )


def normalize_freelancehunt_project(
    project_id: str,
    title: str,
    description: str,
    url: str,
    budget_text: str = "",
) -> NormalizedOrder:
    return NormalizedOrder(
        external_id=f"freelancehunt:{project_id}",
        source="freelancehunt",
        title=title,
        description=description,
        url=url,
        budget_text=budget_text,
        raw={"project_id": project_id},
    )


def normalize_workspace_tender(
    tender_id: str,
    title: str,
    description: str,
    url: str,
    budget_text: str = "",
) -> NormalizedOrder:
    return NormalizedOrder(
        external_id=f"workspace_ru:{tender_id}",
        source="workspace_ru",
        title=title,
        description=description,
        url=url,
        budget_text=budget_text,
        raw={"tender_id": tender_id},
    )


def normalize_weblancer_project(
    project_id: str,
    title: str,
    description: str,
    url: str,
    budget_text: str = "",
) -> NormalizedOrder:
    return NormalizedOrder(
        external_id=f"weblancer:{project_id}",
        source="weblancer",
        title=title,
        description=description,
        url=url,
        budget_text=budget_text,
        raw={"project_id": project_id},
    )


def normalize_hablance_task(
    task_id: str,
    title: str,
    description: str,
    url: str,
    budget_text: str = "",
) -> NormalizedOrder:
    return NormalizedOrder(
        external_id=f"hablance:{task_id}",
        source="hablance",
        title=title,
        description=description,
        url=url,
        budget_text=budget_text,
        raw={"task_id": task_id},
    )
