import logging
import re
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from app.config import get_settings
from app.connectors.base import BaseConnector
from app.core.normalizer import NormalizedOrder, normalize_freelance_ru_task

logger = logging.getLogger(__name__)


class FreelanceRuConnector(BaseConnector):
    """Assist-only: poll listing, open URL + paste draft in bot."""

    name = "freelance_ru"

    def __init__(self):
        self.settings = get_settings()
        self._seen: set[str] = set()

    async def poll(self) -> list[NormalizedOrder]:
        if not self.settings.freelance_ru_enabled:
            return []

        orders: list[NormalizedOrder] = []
        first_run = not self._seen
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(
                    self.settings.freelance_ru_search_url,
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(2500)

                links = await page.query_selector_all("a[href*='/task/view/']")
                for link in links[:40]:
                    href = await link.get_attribute("href")
                    title = (await link.inner_text()).strip()
                    if not href or not title or len(title) < 8:
                        continue
                    tid = self._extract_id(href)
                    if not tid or tid in self._seen:
                        continue
                    self._seen.add(tid)
                    full_url = urljoin("https://freelance.ru", href)
                    orders.append(
                        normalize_freelance_ru_task(tid, title, title, full_url)
                    )

                await browser.close()
                if first_run:
                    logger.info(
                        "Freelance.ru baseline done (%s tasks marked seen)",
                        len(self._seen),
                    )
                    return []
        except Exception:
            logger.exception("Freelance.ru poll failed")
        return orders

    @staticmethod
    def _extract_id(href: str) -> str | None:
        m = re.search(r"/task/view/(\d+)", href)
        return m.group(1) if m else None
