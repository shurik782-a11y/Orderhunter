"""In-process monitor pause/resume for Assist bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MonitorRuntime:
    paused: bool = False
    paused_at: datetime | None = None
    resumed_at: datetime | None = field(default_factory=lambda: datetime.now(UTC))
    last_ingest_at: datetime | None = None
    last_notify_at: datetime | None = None
    last_source: str = ""
    last_title: str = ""

    def pause(self) -> None:
        self.paused = True
        self.paused_at = datetime.now(UTC)

    def resume(self) -> None:
        self.paused = False
        self.resumed_at = datetime.now(UTC)
        self.paused_at = None

    def mark_ingest(self, source: str, title: str) -> None:
        self.last_ingest_at = datetime.now(UTC)
        self.last_source = source
        self.last_title = title[:120]

    def mark_notify(self) -> None:
        self.last_notify_at = datetime.now(UTC)

    def status_label(self) -> str:
        return "⏸ На паузе" if self.paused else "🟢 Ищет заказы"


monitor = MonitorRuntime()
